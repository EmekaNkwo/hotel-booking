"""API tests for the MFA device lifecycle endpoints (M2.5 step 5).

Exercises the full middleware -> view -> serializer -> service chain over the
session-authenticated API. Secret-exposure assertions use the black-box view:
the only plaintext the API ever returns is the provisioning URI (once, at
enrollment); the stored ciphertext and any other secret never appear. Codes
are computed from the plaintext secret recovered from that URI.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.test import Client as DjangoClient

from apps.accounts import totp
from apps.accounts.models import MfaDevice
from tests.api.helpers import login as _login

UserAccount = get_user_model()

OWNER_EMAIL = "owner@acme.example"
OWNER_PASSWORD = "Owner!pw123!"
VIEWER_EMAIL = "viewer@acme.example"
VIEWER_PASSWORD = "Viewer!pw123!"


def _secret_from_uri(uri: str) -> str:
    return parse_qs(urlparse(uri).query)["secret"][0]


def _enroll(client, name="phone") -> dict:
    resp = client.post("/api/mfa/devices/enroll/", {"name": name}, format="json")
    assert resp.status_code == 201, resp.data
    return resp.data


def _verify(client, device_id: int, secret: str):
    code = totp.compute_code(secret)
    return client.post(
        f"/api/mfa/devices/{device_id}/verify/", {"code": code}, format="json"
    )


def _remove(client, device_id: int):
    return client.post(f"/api/mfa/devices/{device_id}/remove/", format="json")


class TestAuth:
    @pytest.mark.django_db
    def test_unauthenticated_requests_are_rejected(self, api, provisioned):
        """403 — the project's session-auth convention (no WWW-Authenticate
        header), consistent with test_tenants.py/test_roles.py."""
        assert api.get("/api/mfa/devices/").status_code == 403
        assert (
            api.post("/api/mfa/devices/enroll/", {"name": "phone"}, format="json").status_code
            == 403
        )
        assert (
            api.post("/api/mfa/devices/1/verify/", {"code": "123456"}, format="json").status_code
            == 403
        )
        assert api.post("/api/mfa/devices/1/remove/", format="json").status_code == 403

    @pytest.mark.django_db
    def test_csrf_enforced_for_authenticated_enroll(self, provisioned):
        """The MFA endpoints share the session+CSRF model: an authenticated
        POST without a CSRF token is rejected (403) before any write."""
        owner = UserAccount.objects.get(email=OWNER_EMAIL)
        client = DjangoClient(enforce_csrf_checks=True)
        client.force_login(owner)

        resp = client.post(
            "/api/mfa/devices/enroll/", {"name": "phone"}, content_type="application/json"
        )

        assert resp.status_code == 403
        assert MfaDevice.objects.count() == 0


class TestEnroll:
    @pytest.mark.django_db
    def test_enroll_returns_device_and_one_shot_uri(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        data = _enroll(api)

        device = data["device"]
        assert device["name"] == "phone"
        assert device["device_type"] == "totp"
        assert device["verified"] is False
        assert device["removed"] is False
        assert data["provisioning_uri"].startswith("otpauth://totp/")

    @pytest.mark.django_db
    def test_plaintext_secret_only_in_the_one_shot_uri(self, api, provisioned):
        """The URI is the ONLY place the plaintext appears; the list endpoint
        never re-exposes it."""
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        secret = _secret_from_uri(_enroll(api)["provisioning_uri"])
        assert len(secret) == 32

        listed = api.get("/api/mfa/devices/")
        assert listed.status_code == 200
        assert secret not in listed.content.decode()

    @pytest.mark.django_db
    def test_stored_ciphertext_and_secret_key_never_exposed(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        device_id = _enroll(api)["device"]["id"]

        stored = MfaDevice.objects.get(pk=device_id).secret_key
        listed = api.get("/api/mfa/devices/")
        assert "secret_key" not in listed.content.decode()
        assert stored not in listed.content.decode()

    @pytest.mark.django_db
    def test_blank_name_is_400(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        resp = api.post("/api/mfa/devices/enroll/", {"name": "  "}, format="json")

        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_webauthn_type_is_400(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        resp = api.post(
            "/api/mfa/devices/enroll/", {"name": "key", "device_type": "webauthn"}, format="json"
        )

        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_duplicate_name_is_409(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        _enroll(api, name="phone")
        resp = api.post("/api/mfa/devices/enroll/", {"name": "phone"}, format="json")

        assert resp.status_code == 409


class TestVerify:
    @pytest.mark.django_db
    def test_verify_success_returns_204(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        data = _enroll(api)

        resp = _verify(api, data["device"]["id"], _secret_from_uri(data["provisioning_uri"]))

        assert resp.status_code == 204

    @pytest.mark.django_db
    def test_verify_wrong_code_is_400(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        device_id = _enroll(api)["device"]["id"]
        resp = api.post(
            f"/api/mfa/devices/{device_id}/verify/", {"code": "000000"}, format="json"
        )

        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_reverify_is_idempotent_204(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        data = _enroll(api)
        secret = _secret_from_uri(data["provisioning_uri"])
        device_id = data["device"]["id"]

        assert _verify(api, device_id, secret).status_code == 204
        assert _verify(api, device_id, secret).status_code == 204

    @pytest.mark.django_db
    def test_verify_unknown_device_is_404(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        resp = api.post("/api/mfa/devices/9999/verify/", {"code": "123456"}, format="json")

        assert resp.status_code == 404


class TestIsolation:
    @pytest.mark.django_db
    def test_cross_user_verify_is_404(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        data = _enroll(api)
        secret = _secret_from_uri(data["provisioning_uri"])
        device_id = data["device"]["id"]

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = _verify(api, device_id, secret)

        assert resp.status_code == 404  # not found — never a leak of existence

    @pytest.mark.django_db
    def test_cross_user_remove_is_404(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        device_id = _enroll(api)["device"]["id"]

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = _remove(api, device_id)

        assert resp.status_code == 404
        assert MfaDevice.objects.get(pk=device_id).removed_at is None


class TestRemove:
    @pytest.mark.django_db
    def test_remove_success_returns_204(self, api, provisioned):
        """Uses the viewer — the owner is blocked by the last-device guard (its
        own test)."""
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        data = _enroll(api)
        _verify(api, data["device"]["id"], _secret_from_uri(data["provisioning_uri"]))

        resp = _remove(api, data["device"]["id"])

        assert resp.status_code == 204
        assert MfaDevice.objects.get(pk=data["device"]["id"]).removed_at is not None

    @pytest.mark.django_db
    def test_unverified_device_cannot_be_removed_409(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        device_id = _enroll(api)["device"]["id"]

        resp = _remove(api, device_id)

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_removed_device_verify_is_409_and_list_shows_removed(self, api, provisioned):
        """Uses the viewer: the owner cannot remove their only verified device
        (last-device guard), which is the subject of its own test."""
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        data = _enroll(api)
        secret = _secret_from_uri(data["provisioning_uri"])
        device_id = data["device"]["id"]
        _verify(api, device_id, secret)
        _remove(api, device_id)

        assert _verify(api, device_id, secret).status_code == 409
        listed = api.get("/api/mfa/devices/").data
        assert [d for d in listed if d["id"] == device_id][0]["removed"] is True


class TestLastDeviceGuard:
    @pytest.mark.django_db
    def test_owner_removing_only_verified_device_is_409(self, api, provisioned):
        """tenant_owner cannot be left without MFA (SDD 14.1)."""
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        data = _enroll(api)
        secret = _secret_from_uri(data["provisioning_uri"])
        device_id = data["device"]["id"]
        _verify(api, device_id, secret)

        resp = _remove(api, device_id)

        assert resp.status_code == 409
        assert MfaDevice.objects.get(pk=device_id).removed_at is None

    @pytest.mark.django_db
    def test_viewer_can_remove_only_verified_device(self, api, provisioned):
        """A user without an MFA-required role is not blocked."""
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        data = _enroll(api)
        secret = _secret_from_uri(data["provisioning_uri"])
        device_id = data["device"]["id"]
        _verify(api, device_id, secret)

        resp = _remove(api, device_id)

        assert resp.status_code == 204


class TestSchema:
    @pytest.mark.django_db
    def test_openapi_schema_validates_and_includes_mfa_endpoints(self):
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema

        schema = SchemaGenerator().get_schema(request=None, public=True)
        validate_schema(schema)  # raises SchemaValidationError on problems

        paths = schema["paths"]
        assert "/api/mfa/devices/" in paths
        assert "/api/mfa/devices/enroll/" in paths
        assert "/api/mfa/devices/{device_id}/verify/" in paths
        assert "/api/mfa/devices/{device_id}/remove/" in paths

        enroll_resp = paths["/api/mfa/devices/enroll/"]["post"]["responses"]["201"]
        schema_ref = enroll_resp["content"]["application/json"]["schema"]["$ref"]
        enroll_schema = schema["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]
        assert enroll_schema["properties"]["provisioning_uri"]["type"] == "string"
        assert "device" in enroll_schema["properties"]
