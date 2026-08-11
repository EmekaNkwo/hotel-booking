"""API tests for the two-step session login (M2.5 step 6).

Flow under test:

    password ok -> MFA required? --No--> authenticated session
                              |
                             Yes
                              |
                    202 {requires_mfa} + pending challenge in session
                              |
                     POST /api/auth/mfa/ {code}
                      |-> invalid/expired/malformed/replayed -> 401, never auth
                      `-> MfaService.verify_code() ok -> session flushed,
                          login() -> authenticated session (new session id)

A user with a verified MFA device (owner/tenant_owner) is challenged; a user
without one (viewer) logs in exactly as before. The MfaLoginView is the only
new moving part — TOTP verification stays in MfaService.
"""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone

from apps.accounts import totp
from tests.api.helpers import login as _login

UserAccount = get_user_model()

OWNER_EMAIL = "owner@acme.example"
OWNER_PASSWORD = "Owner!pw123!"
VIEWER_EMAIL = "viewer@acme.example"
VIEWER_PASSWORD = "Viewer!pw123!"


def _secret_from_uri(uri: str) -> str:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(uri).query)["secret"][0]


def _give_owner_a_verified_device(api) -> str:
    """Enroll + verify a device for the owner; returns the TOTP secret.

    The owner starts with no device, so the first login is a normal 200; after
    enrollment/verification the account requires a challenge on every login.
    """
    assert _login(api, OWNER_EMAIL, OWNER_PASSWORD).status_code == 200
    enrolled = api.post("/api/mfa/devices/enroll/", {"name": "phone"}, format="json")
    assert enrolled.status_code == 201, enrolled.data
    secret = _secret_from_uri(enrolled.data["provisioning_uri"])
    device_id = enrolled.data["device"]["id"]
    assert (
        api.post(
            f"/api/mfa/devices/{device_id}/verify/",
            {"code": totp.compute_code(secret)},
            format="json",
        ).status_code
        == 204
    )
    api.post("/api/auth/logout/")
    return secret


def _session_id(api) -> str:
    return api.cookies["sessionid"].value


class TestPasswordOnlyStillWorks:
    @pytest.mark.django_db
    def test_user_without_device_logs_in_normally(self, api, provisioned):
        """The viewer has no verified device -> the existing single-step login."""
        resp = _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        assert resp.status_code == 200
        assert "requires_mfa" not in resp.data
        assert api.get("/api/auth/me/").status_code == 200


class TestChallenge:
    @pytest.mark.django_db
    def test_mfa_user_gets_no_authenticated_session_from_password_alone(self, api, provisioned):
        _give_owner_a_verified_device(api)

        resp = _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        assert resp.status_code == 202
        assert resp.data["requires_mfa"] is True
        # The password was verified, but no authenticated session exists yet.
        assert api.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_challenge_response_shape(self, api, provisioned):
        _give_owner_a_verified_device(api)

        resp = _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        assert resp.data["requires_mfa"] is True
        assert resp.data["expires_in"] == settings.MFA_PENDING_TIMEOUT_SECONDS

    @pytest.mark.django_db
    def test_prior_authenticated_session_is_not_left_during_pending(self, api, provisioned):
        """A user who was already logged in is logged OUT when a fresh login
        enters the MFA-pending state (no accidental half-auth)."""
        # Owner logs in normally (no device yet) -> an authenticated session.
        assert _login(api, OWNER_EMAIL, OWNER_PASSWORD).status_code == 200
        assert api.get("/api/auth/me/").status_code == 200

        # Owner enrolls + verifies a device -> MFA now required, still authenticated.
        enrolled = api.post("/api/mfa/devices/enroll/", {"name": "phone"}, format="json")
        secret = _secret_from_uri(enrolled.data["provisioning_uri"])
        device_id = enrolled.data["device"]["id"]
        assert (
            api.post(
                f"/api/mfa/devices/{device_id}/verify/",
                {"code": totp.compute_code(secret)},
                format="json",
            ).status_code
            == 204
        )
        assert api.get("/api/auth/me/").status_code == 200

        # Re-login: enters the MFA-pending state -> the pre-existing authenticated
        # session must be flushed, not silently kept half-authenticated.
        resp = _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        assert resp.status_code == 202
        assert api.get("/api/auth/me/").status_code == 403


class TestMfaCompletion:
    @pytest.mark.django_db
    def test_valid_code_completes_login(self, api, provisioned):
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)  # 202 pending

        resp = api.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")

        assert resp.status_code == 200
        assert resp.data["user"]["email"] == OWNER_EMAIL
        assert api.get("/api/auth/me/").status_code == 200

    @pytest.mark.django_db
    def test_invalid_code_does_not_authenticate(self, api, provisioned):
        _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        resp = api.post("/api/auth/mfa/", {"code": "000000"}, format="json")

        assert resp.status_code == 401
        assert api.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_wrong_code_does_not_complete_the_challenge(self, api, provisioned):
        """The challenge is bound to the owner: only the owner's code completes it."""
        _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        resp = api.post("/api/auth/mfa/", {"code": "111111"}, format="json")

        assert resp.status_code == 401
        assert api.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_challenge_cannot_be_used_from_another_session(self, api, provisioned):
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)  # owner's client holds the pending challenge

        from rest_framework.test import APIClient

        other = APIClient()  # no pending challenge in this session
        resp = other.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")

        assert resp.status_code == 401
        assert other.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_missing_code_is_400(self, api, provisioned):
        _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        resp = api.post("/api/auth/mfa/", {}, format="json")

        assert resp.status_code == 400


class TestReplayAndExpiry:
    @pytest.mark.django_db
    def test_expired_challenge_does_not_authenticate(self, api, provisioned):
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        pending_sid = _session_id(api)

        store = SessionStore(session_key=pending_sid)
        store.load()
        store["mfa_pending"]["expires_at"] = (
            timezone.now() - timezone.timedelta(seconds=1)
        ).isoformat()
        store.save()

        resp = api.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")

        assert resp.status_code == 401
        assert api.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_consumed_challenge_cannot_be_replayed(self, api, provisioned):
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        pending_sid = _session_id(api)
        code = totp.compute_code(secret)

        assert api.post("/api/auth/mfa/", {"code": code}, format="json").status_code == 200

        # Replay the same code from the SAME pre-auth session id: that session
        # was flushed on success, so the challenge is gone -> 401.
        api.cookies["sessionid"] = pending_sid
        resp = api.post("/api/auth/mfa/", {"code": code}, format="json")

        assert resp.status_code == 401
        assert api.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_malformed_challenge_fails_closed(self, api, provisioned):
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        pending_sid = _session_id(api)

        store = SessionStore(session_key=pending_sid)
        store.load()
        store["mfa_pending"] = {"user_id": "not-an-int", "expires_at": "garbage"}
        store.save()

        resp = api.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")

        assert resp.status_code == 401


class TestInactiveUsers:
    @pytest.mark.django_db
    def test_locked_user_cannot_start_login(self, api, provisioned):
        _give_owner_a_verified_device(api)
        UserAccount.objects.filter(email=OWNER_EMAIL).update(status="locked")

        resp = _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        assert resp.status_code == 401

    @pytest.mark.django_db
    def test_deactivated_user_cannot_start_login(self, api, provisioned):
        _give_owner_a_verified_device(api)
        UserAccount.objects.filter(email=OWNER_EMAIL).update(status="deactivated")

        resp = _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        assert resp.status_code == 401

    @pytest.mark.django_db
    def test_locked_between_steps_cannot_complete_login(self, api, provisioned):
        """A lockout landing after the password step but before the MFA step
        still blocks the final authentication."""
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)  # 202 pending

        UserAccount.objects.filter(email=OWNER_EMAIL).update(status="locked")

        resp = api.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")

        assert resp.status_code == 401
        assert api.get("/api/auth/me/").status_code == 403


class TestSessionFixation:
    @pytest.mark.django_db
    def test_session_id_rotates_on_final_authentication(self, api, provisioned):
        """The pre-auth session identifier never becomes the authenticated one."""
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        pending_sid = _session_id(api)

        resp = api.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")

        assert resp.status_code == 200
        assert _session_id(api) != pending_sid


class TestCsrfModel:
    @pytest.mark.django_db
    def test_anonymous_mfa_endpoint_matches_login_csrf_model(self, api, provisioned):
        """Like the password login, the MFA completion is a pre-auth endpoint:
        SessionAuthentication only enforces CSRF once a session is
        authenticated, so a plain session POST works."""
        secret = _give_owner_a_verified_device(api)
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        resp = api.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")

        assert resp.status_code == 200
