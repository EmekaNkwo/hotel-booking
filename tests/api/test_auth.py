"""API tests for auth endpoints — login, logout, me (M2.3).

Every test exercises the full middleware → view → service chain: the middleware
resolves the principal from the session cookie, and DRF validates it too.
"""

import pytest

from apps.accounts.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    RolePermission,
    RoleStatus,
    UserAccount,
)
from tests.api.helpers import login as _login


class TestLogin:
    @pytest.mark.django_db
    def test_success_returns_user_and_memberships(self, api, provisioned):
        resp = _login(api, "owner@acme.example", "Owner!pw123!")

        assert resp.status_code == 200
        assert resp.data["user"]["email"] == "owner@acme.example"
        assert len(resp.data["memberships"]) >= 1

    @pytest.mark.django_db
    def test_wrong_password_returns_401(self, api, provisioned):
        resp = _login(api, "owner@acme.example", "wrong")

        assert resp.status_code == 401

    @pytest.mark.django_db
    def test_missing_fields_returns_400(self, api, provisioned):
        resp = api.post("/api/auth/login/", {"email": "owner@acme.example"}, format="json")

        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_inactive_user_cannot_login(self, api, provisioned):
        UserAccount.objects.filter(email="owner@acme.example").update(status="locked")

        resp = _login(api, "owner@acme.example", "Owner!pw123!")

        assert resp.status_code == 401


class TestLogout:
    @pytest.mark.django_db
    def test_logout_destroys_session(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post("/api/auth/logout/")

        assert resp.status_code == 204
        assert api.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_unauthenticated_logout_returns_403(self, api, provisioned):
        assert api.post("/api/auth/logout/").status_code == 403


class TestMe:
    @pytest.mark.django_db
    def test_returns_user_and_resolved_tenant(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")
        resp = api.get("/api/auth/me/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 200
        assert resp.data["user"]["email"] == "owner@acme.example"
        assert resp.data["tenant_id"] == 1

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, provisioned):
        assert api.get("/api/auth/me/").status_code == 403

    @pytest.mark.django_db
    def test_multi_membership_without_header_resolves_to_none(self, api, provisioned):
        _, _, _, _, viewer, _ = provisioned
        _create_tenant2(viewer)
        _login(api, "viewer@acme.example", "Viewer!pw123!")

        resp = api.get("/api/auth/me/")

        assert resp.data["tenant_id"] is None  # multiple tenants → no implicit selection

    @pytest.mark.django_db
    def test_single_membership_auto_selects(self, api, provisioned):
        _login(api, "viewer@acme.example", "Viewer!pw123!")

        resp = api.get("/api/auth/me/")

        assert resp.data["tenant_id"] == 1  # sole active membership auto-selected


def _create_tenant2(viewer_user):
    """Create a second tenant and grant the viewer access (multi-membership case)."""
    from apps.tenants.models import Tenant

    t2 = Tenant.objects.create(
        code="globex", name="Globex", base_currency="NGN", status="active"
    )
    role = Role.objects.create(tenant_id=t2.pk, name="staff", status=RoleStatus.PUBLISHED)
    m = Membership.objects.create(
        tenant_id=t2.pk, user_account=viewer_user, status=MembershipStatus.ACTIVE
    )
    RolePermission.objects.create(role=role, tenant_id=t2.pk, permission_code="member.view")
    MembershipRole.objects.create(membership=m, role=role, tenant_id=t2.pk)
    return t2
