"""API tests for the member endpoints — list and invite (M2.3).

The central M2.3 teaching point: tenant isolation at the API layer. A user in
tenant A must not be able to read or write tenant B's rows — even with a
valid X-Tenant-Id header for tenant B, the middleware rejects non-members.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    RolePermission,
    RoleStatus,
)
from apps.tenants.models import Tenant
from apps.tenants.services import TenantService
from tests.api.helpers import login as _login


def _provision_second_tenant(owner_email, owner_password):
    """Provision tenant "beta" with an owner who carries every permission.

    ``TenantService.provision`` already grants all tenant-scoped permissions to
    the ``tenant_owner`` role, so the owner can read members without any extra
    grant.
    """
    TenantService.provision(
        code="beta", name="Beta", base_currency="NGN", owner_email=owner_email
    )
    beta = Tenant.objects.get(code="beta")
    owner = get_user_model().objects.get(email=owner_email)
    owner.set_password(owner_password)
    owner.save()
    return beta, owner


class TestMemberList:
    @pytest.mark.django_db
    def test_owner_can_list_members(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.get("/api/members/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 200
        emails = [m["email"] for m in resp.data]
        assert "owner@acme.example" in emails
        assert "viewer@acme.example" in emails

    @pytest.mark.django_db
    def test_viewer_with_member_view_can_list(self, api, provisioned):
        _login(api, "viewer@acme.example", "Viewer!pw123!")

        resp = api.get("/api/members/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, provisioned):
        assert api.get("/api/members/", HTTP_X_TENANT_ID="1").status_code == 403

    @pytest.mark.django_db
    def test_requires_a_tenant_context(self, api, provisioned):
        """A user with multiple memberships and no X-Tenant-Id gets no context."""
        _, _, _, _, viewer, _ = provisioned
        _grant_viewer_second_tenant(viewer)

        _login(api, "viewer@acme.example", "Viewer!pw123!")
        resp = api.get("/api/members/")  # no header, multi-membership → 403

        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_user_without_member_view_gets_403(self, api, provisioned):
        from apps.accounts.models import UserAccount

        roleless = UserAccount.objects.create_user(
            email="roleless@example.com", password="Roleless!pw123"
        )
        acme = Tenant.objects.get(code="acme")
        Membership.objects.create(
            tenant_id=acme.pk, user_account=roleless, status=MembershipStatus.ACTIVE
        )

        _login(api, "roleless@example.com", "Roleless!pw123")
        resp = api.get("/api/members/", HTTP_X_TENANT_ID=str(acme.pk))

        assert resp.status_code == 403


class TestTenantIsolation:
    @pytest.mark.django_db
    def test_member_of_tenant_a_cannot_read_tenant_b(self, api, provisioned):
        """Cross-tenant isolation: acme's owner cannot see Beta's members."""
        beta, _ = _provision_second_tenant("beta@acme.example", "Beta!pw123")

        # The acme owner tries to read Beta — not a member → 403.
        _login(api, "owner@acme.example", "Owner!pw123!")
        resp = api.get("/api/members/", HTTP_X_TENANT_ID=str(beta.pk))

        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_member_of_tenant_b_reads_only_their_own(self, api, provisioned):
        """Beta's owner sees Beta members but never acme members."""
        beta, _ = _provision_second_tenant("beta@acme.example", "Beta!pw123")

        _login(api, "beta@acme.example", "Beta!pw123")
        resp = api.get("/api/members/", HTTP_X_TENANT_ID=str(beta.pk))

        assert resp.status_code == 200
        emails = {m["email"] for m in resp.data}
        assert "beta@acme.example" in emails
        assert "owner@acme.example" not in emails  # acme members invisible


class TestInviteMember:
    @pytest.mark.django_db
    def test_owner_can_invite_and_receives_a_token(self, api, provisioned):
        _, _, _, fd_role, _, _ = provisioned
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post(
            "/api/members/invite/",
            {"email": "new-hire@acme.example", "role_id": fd_role.pk},
            format="json",
            HTTP_X_TENANT_ID="1",
        )

        assert resp.status_code == 201
        assert resp.data["token"]  # the one-time raw token is returned
        assert resp.data["email"] == "new-hire@acme.example"

    @pytest.mark.django_db
    def test_inviting_role_from_another_tenant_is_404(self, api, provisioned):
        foreign_role = Role.objects.create(tenant_id=999, name="rogue")
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post(
            "/api/members/invite/",
            {"email": "x@acme.example", "role_id": foreign_role.pk},
            format="json",
            HTTP_X_TENANT_ID="1",
        )

        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_viewer_without_invite_permission_gets_403(self, api, provisioned):
        _, _, _, fd_role, _, _ = provisioned
        _login(api, "viewer@acme.example", "Viewer!pw123!")

        resp = api.post(
            "/api/members/invite/",
            {"email": "x@acme.example", "role_id": fd_role.pk},
            format="json",
            HTTP_X_TENANT_ID="1",
        )

        assert resp.status_code == 403


def _grant_viewer_second_tenant(viewer):
    """Grant the viewer a membership in a second tenant (multi-membership case)."""
    t2 = Tenant.objects.create(code="globex", name="Globex", base_currency="NGN", status="active")
    r2 = Role.objects.create(tenant_id=t2.pk, name="staff", status=RoleStatus.PUBLISHED)
    m2 = Membership.objects.create(
        tenant_id=t2.pk, user_account=viewer, status=MembershipStatus.ACTIVE
    )
    RolePermission.objects.create(role=r2, tenant_id=t2.pk, permission_code="member.view")
    MembershipRole.objects.create(membership=m2, role=r2, tenant_id=t2.pk)


class TestRevokeMember:
    """Revoke endpoint: lifecycle, permission, isolation (M2.4)."""

    @pytest.mark.django_db
    def test_owner_can_revoke_a_member(self, api, provisioned):
        _, _, _, _, viewer, viewer_membership = provisioned
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post(f"/api/members/{viewer_membership.pk}/revoke/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 204
        viewer_membership.refresh_from_db()
        assert viewer_membership.status == MembershipStatus.REVOKED
        assert not viewer_membership.roles.exists()
        from apps.shared.models import AuditLog

        assert AuditLog.objects.filter(
            entity_type="membership", action="membership.revoked"
        ).exists()

    @pytest.mark.django_db
    def test_revoke_requires_member_manage(self, api, provisioned):
        # The viewer carries only member.view — revoking is forbidden.
        _, _, owner_membership, _, _, _ = provisioned
        _login(api, "viewer@acme.example", "Viewer!pw123!")

        resp = api.post(f"/api/members/{owner_membership.pk}/revoke/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_cross_tenant_revoke_is_forbidden(self, api, provisioned):
        # The acme owner is not a member of beta — the middleware rejects the
        # attempt before any permission check runs.
        beta, _ = _provision_second_tenant("beta@acme.example", "Beta!pw123")
        _, _, _, _, viewer, viewer_membership = provisioned
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post(
            f"/api/members/{viewer_membership.pk}/revoke/", HTTP_X_TENANT_ID=str(beta.pk)
        )

        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_owner_cannot_revoke_own_last_owner_membership(self, api, provisioned):
        _, _, owner_membership, _, _, _ = provisioned
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post(f"/api/members/{owner_membership.pk}/revoke/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_revoking_an_unknown_membership_is_404(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post("/api/members/999999/revoke/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 404
