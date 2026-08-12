"""API tests for the tenant-sensitive MFA enforcement middleware (M2.5 step 7).

The middleware denies an authenticated user whose ACTIVE membership in the
effective tenant carries an MFA-required role (tenant_owner) when the session
lacks MFA assurance for THAT tenant. Assurance (``mfa_verified_tenants``) is
stamped by the Step 6 login flow from the principal's own memberships — never
from a client-supplied field. These tests prove the enforcement, its
tenant-sensitivity, and that the device/auth endpoints stay reachable.
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
from apps.tenants.models import Tenant
from apps.tenants.services import TenantService

from tests.api.helpers import (
    enroll_verified_device,
    equip_owner_with_mfa,
    login as _login,
    login_mfa,
)

OWNER_EMAIL = "owner@acme.example"
OWNER_PASSWORD = "Owner!pw123!"
VIEWER_EMAIL = "viewer@acme.example"
VIEWER_PASSWORD = "Viewer!pw123!"

ACME = "1"


class TestAllowed:
    @pytest.mark.django_db
    def test_non_mfa_required_user_is_not_blocked(self, api, provisioned):
        """The viewer (front_desk, no MFA-required role) behaves as before."""
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/members/", HTTP_X_TENANT_ID=ACME)

        assert resp.status_code == 200  # member.view grants access

    @pytest.mark.django_db
    def test_mfa_required_owner_with_assurance_is_not_blocked(self, api, owner_mfa):
        """owner_mfa pre-equips the device; login_mfa walks challenge -> code
        and stamps the session, so protected operations are reachable."""
        login_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)

        resp = api.get("/api/members/", HTTP_X_TENANT_ID=ACME)

        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_unauthenticated_behavior_is_unchanged(self, api, provisioned):
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 403


class TestEnforcement:
    @pytest.mark.django_db
    def test_owner_without_mfa_cannot_access_protected_operations(self, api, provisioned):
        """A tenant_owner with a valid session but no MFA assurance is denied
        before any RBAC/service logic runs."""
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)  # 200: no device -> no challenge
        assert api.get("/api/auth/me/").status_code == 200  # identity still readable

        resp = api.get("/api/members/", HTTP_X_TENANT_ID=ACME)

        assert resp.status_code == 403

        # Writes are blocked too.
        resp = api.post(
            "/api/roles/create/",
            {"name": "housekeeping", "permission_codes": ["member.view"]},
            format="json",
            HTTP_X_TENANT_ID=ACME,
        )
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_mfa_completion_establishes_assurance(self, api, provisioned):
        """The Step 6 flow is what grants assurance — password alone never does."""
        secret = equip_owner_with_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        assert api.get("/api/auth/me/").status_code == 403  # logged out by setup

        resp = _login(api, OWNER_EMAIL, OWNER_PASSWORD)  # 202 pending
        assert resp.status_code == 202
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 403

        from apps.accounts import totp

        assert (
            api.post("/api/auth/mfa/", {"code": totp.compute_code(secret)}, format="json")
            .status_code
            == 200
        )
        assert 1 in api.session.get("mfa_verified_tenants", [])
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 200

    @pytest.mark.django_db
    def test_assurance_cannot_be_forged_by_client_field(self, api, provisioned):
        """The stamp lives in the server session; a client header or payload
        field cannot fabricate it."""
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        get_resp = api.get(
            "/api/members/", HTTP_X_TENANT_ID=ACME, HTTP_X_MFA_VERIFIED="1"
        )
        post_resp = api.post(
            "/api/members/invite/",
            {"email": "x@acme.example", "role_id": 1, "mfa_verified": True},
            format="json",
            HTTP_X_TENANT_ID=ACME,
        )

        assert get_resp.status_code == 403
        assert post_resp.status_code == 403


class TestTenantSensitivity:
    @pytest.mark.django_db
    def test_new_mfa_required_tenant_after_login_is_not_inherited(self, api, provisioned):
        """'Completed MFA once' does NOT satisfy a tenant granted afterwards."""
        equip_owner_with_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        login_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 200

        # Grant the owner the tenant_owner role in a NEW tenant mid-session.
        beta = TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta@acme.example"
        )
        owner = UserAccount.objects.get(email=OWNER_EMAIL)
        membership = Membership.objects.create(
            tenant_id=beta.pk, user_account=owner, status=MembershipStatus.ACTIVE
        )
        owner_role = Role.objects.get(tenant_id=beta.pk, name="tenant_owner")
        MembershipRole.objects.create(membership=membership, role=owner_role, tenant_id=beta.pk)

        assert beta.pk not in api.session.get("mfa_verified_tenants", [])
        resp = api.get("/api/members/", HTTP_X_TENANT_ID=str(beta.pk))

        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_non_required_tenant_needs_no_assurance(self, api, provisioned):
        """Switching to a tenant where the user holds no MFA-required role is
        not gated — the policy is evaluated against the effective tenant."""
        equip_owner_with_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        login_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)

        beta = TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta@acme.example"
        )
        owner = UserAccount.objects.get(email=OWNER_EMAIL)
        membership = Membership.objects.create(
            tenant_id=beta.pk, user_account=owner, status=MembershipStatus.ACTIVE
        )
        fd_role = Role.objects.create(
            tenant_id=beta.pk, name="front_desk", status=RoleStatus.PUBLISHED
        )
        RolePermission.objects.create(
            role=fd_role, tenant_id=beta.pk, permission_code="member.view"
        )
        MembershipRole.objects.create(membership=membership, role=fd_role, tenant_id=beta.pk)

        resp = api.get("/api/members/", HTTP_X_TENANT_ID=str(beta.pk))

        assert resp.status_code == 200  # front_desk in beta: member.view, no MFA gate


class TestRoleAndMembershipChanges:
    @pytest.mark.django_db
    def test_revoked_membership_invalidates_access(self, api, provisioned):
        equip_owner_with_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        login_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 200

        Membership.objects.filter(
            user_account__email=OWNER_EMAIL, tenant_id=1, status=MembershipStatus.ACTIVE
        ).update(status=MembershipStatus.REVOKED)

        # acme is no longer a principal tenant -> no context -> 403.
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 403

    @pytest.mark.django_db
    def test_owner_role_grant_and_removal_switch_enforcement(self, api, provisioned):
        """The requirement is evaluated live against the effective membership:
        promoting a member to owner blocks until fresh MFA; removing the role
        unblocks."""
        acme = Tenant.objects.get(code="acme")
        desk = UserAccount.objects.create_user(email="desk@acme.example", password="Desk!pw123")
        membership = Membership.objects.create(
            tenant_id=acme.pk, user_account=desk, status=MembershipStatus.ACTIVE
        )
        fd_role = Role.objects.get(tenant_id=acme.pk, name="front_desk")
        MembershipRole.objects.create(membership=membership, role=fd_role, tenant_id=acme.pk)

        _login(api, "desk@acme.example", "Desk!pw123")  # no device -> 200, unstamped
        assert api.get("/api/members/", HTTP_X_TENANT_ID=str(acme.pk)).status_code == 200

        # Promote mid-session: now MFA-required and NOT satisfied -> blocked.
        owner_role = Role.objects.get(tenant_id=acme.pk, name="tenant_owner")
        MembershipRole.objects.create(membership=membership, role=owner_role, tenant_id=acme.pk)
        assert api.get("/api/members/", HTTP_X_TENANT_ID=str(acme.pk)).status_code == 403

        # Remove the owner role: requirement gone -> allowed again.
        MembershipRole.objects.filter(membership=membership, role=owner_role).delete()
        assert api.get("/api/members/", HTTP_X_TENANT_ID=str(acme.pk)).status_code == 200

    @pytest.mark.django_db
    def test_locked_account_cannot_bypass(self, api, provisioned):
        equip_owner_with_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        login_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 200

        UserAccount.objects.filter(email=OWNER_EMAIL).update(status="locked")

        # Auth middleware resolves AnonymousUser (ModelBackend.get_user -> None)
        # -> not authenticated -> 403, MFA or not.
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 403


class TestExemptSurface:
    @pytest.mark.django_db
    def test_owner_can_enroll_and_verify_a_device_while_required(self, api, provisioned):
        """The chicken-and-egg break: an MFA-required owner with no device can
        set one up through the device API before any login stamps the session."""
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)

        enroll_verified_device(api)

        listed = api.get("/api/mfa/devices/")
        assert listed.status_code == 200
        assert listed.data[0]["verified"] is True

    @pytest.mark.django_db
    def test_owner_can_logout_while_required(self, api, provisioned):
        _login(api, OWNER_EMAIL, OWNER_PASSWORD)
        assert api.get("/api/members/", HTTP_X_TENANT_ID=ACME).status_code == 403

        resp = api.post("/api/auth/logout/")

        assert resp.status_code == 204
        assert api.get("/api/auth/me/").status_code == 403
