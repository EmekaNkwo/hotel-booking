"""Shared helpers for the API tests.

``login`` is the raw password endpoint (Step 6 may return 202 for MFA users).
``login_mfa`` transparently completes the two-step login, and
``equip_owner_with_mfa`` / ``enroll_verified_device`` give an account a
verified TOTP device — the fixture-side setup RBAC tests need now that a
``tenant_owner`` without MFA assurance is denied by the Step 7 middleware.
"""

from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model

from apps.accounts import security, totp
from apps.accounts.models import MfaDevice


def login(client, email, password):
    """Establish a session via the real login endpoint."""
    return client.post(
        "/api/auth/login/",
        {"email": email, "password": password},
        format="json",
    )


def _secret_from_uri(uri: str) -> str:
    return parse_qs(urlparse(uri).query)["secret"][0]


def enroll_verified_device(client, name="phone") -> str:
    """The logged-in user enrolls + verifies a TOTP device; returns the secret.

    Requires a session that is authenticated and NOT yet MFA-challenged (the
    Step 7 middleware exempts the device endpoints precisely so a fresh owner
    can set one up).
    """
    enrolled = client.post("/api/mfa/devices/enroll/", {"name": name}, format="json")
    assert enrolled.status_code == 201, enrolled.data
    secret = _secret_from_uri(enrolled.data["provisioning_uri"])
    device_id = enrolled.data["device"]["id"]
    resp = client.post(
        f"/api/mfa/devices/{device_id}/verify/",
        {"code": totp.compute_code(secret)},
        format="json",
    )
    assert resp.status_code == 204, resp.data
    return secret


def equip_owner_with_mfa(client, email, password) -> str:
    """First-time MFA setup for an MFA-required role holder.

    Plain login (no device yet -> no challenge), enroll + verify a device,
    then log out so a subsequent ``login_mfa`` goes through the full two-step
    flow and stamps the session.
    """
    resp = login(client, email, password)
    assert resp.status_code == 200, resp.data
    secret = enroll_verified_device(client)
    assert client.post("/api/auth/logout/").status_code == 204
    return secret


def login_mfa(client, email, password):
    """Log in, completing the MFA challenge when the account requires it.

    Returns the final response: a 200 authenticated session (stamped with MFA
    assurance for the account's active tenants) for an MFA-equipped account,
    or the plain password-login response for an account without a device.
    """
    resp = login(client, email, password)
    if resp.status_code != 202:
        return resp
    user = get_user_model().objects.get(email=email)
    device = (
        MfaDevice.objects.filter(
            user_account=user, verified_at__isnull=False, removed_at__isnull=True
        )
        .order_by("-created_at")
        .first()
    )
    assert device is not None, f"{email} is challenged but has no verified device"
    secret = security.decrypt_secret(device.secret_key)
    return client.post(
        "/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json"
    )
