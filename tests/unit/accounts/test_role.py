"""Unit tests for RBAC-as-data — the permission registry and the role models.

Order: registry → Role lifecycle/constraints → RolePermission CASCADE →
MembershipRole → the authorization read (has_permission).
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.accounts.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    RolePermission,
    RoleStatus,
)
from apps.accounts.permissions import PERMISSION_CODES, SEEDED_ROLES, is_valid

UserAccount = get_user_model()


def _tenant_scoped_role(tenant_id: int, name: str = "front_desk") -> Role:
    return Role.objects.create(tenant_id=tenant_id, name=name)


def _active_membership(tenant_id: int, email: str = "user@example.com") -> Membership:
    user = UserAccount.objects.create_user(email=email)
    return Membership.objects.create(
        tenant_id=tenant_id, user_account=user, status=MembershipStatus.ACTIVE
    )


class TestPermissionRegistry:
    def test_codes_are_closed_and_well_formed(self):
        for code in PERMISSION_CODES:
            assert code.count(".") == 1  # <domain>.<action>

    def test_is_valid_accepts_known_and_rejects_unknown(self):
        assert is_valid("member.invite")
        assert not is_valid("member.invite_everyone")
        assert not is_valid("")

    def test_seeded_roles_reference_only_registry_codes(self):
        for codes in SEEDED_ROLES.values():
            assert codes <= PERMISSION_CODES


class TestRole:
    @pytest.mark.django_db
    def test_defaults_to_draft(self):
        role = Role.objects.create(tenant_id=1, name="night_manager")

        assert role.status == RoleStatus.DRAFT

    @pytest.mark.django_db
    def test_name_is_unique_within_a_tenant(self):
        _tenant_scoped_role(1, "front_desk")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                _tenant_scoped_role(1, "front_desk")

    @pytest.mark.django_db
    def test_same_name_is_allowed_across_tenants(self):
        _tenant_scoped_role(1, "front_desk")
        _tenant_scoped_role(2, "front_desk")

        assert Role.objects.count() == 2

    @pytest.mark.django_db
    def test_invalid_status_is_blocked(self):
        role = Role(tenant_id=1, name="rogue", status="half-published")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                role.save()

    @pytest.mark.django_db
    def test_retired_role_survives(self):
        role = _tenant_scoped_role(1)
        role.status = RoleStatus.RETIRED
        role.save()

        assert Role.objects.get(pk=role.pk).status == RoleStatus.RETIRED


class TestRolePermission:
    @pytest.mark.django_db
    def test_carries_the_role_and_code(self):
        role = _tenant_scoped_role(1)
        RolePermission.objects.create(role=role, tenant_id=1, permission_code="member.view")

        assert role.permissions.get().permission_code == "member.view"

    @pytest.mark.django_db
    def test_code_is_unique_per_role(self):
        role = _tenant_scoped_role(1)
        RolePermission.objects.create(role=role, tenant_id=1, permission_code="member.view")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                RolePermission.objects.create(
                    role=role, tenant_id=1, permission_code="member.view"
                )

    @pytest.mark.django_db
    def test_deleting_the_role_cascades_its_permissions(self):
        role = _tenant_scoped_role(1)
        RolePermission.objects.create(role=role, tenant_id=1, permission_code="member.view")

        role.delete()

        assert RolePermission.objects.count() == 0


class TestMembershipRole:
    @pytest.mark.django_db
    def test_grants_a_role_to_a_membership(self):
        membership = _active_membership(1)
        role = _tenant_scoped_role(1, "front_desk")

        MembershipRole.objects.create(membership=membership, role=role, tenant_id=1)

        assert membership.roles.get().role == role

    @pytest.mark.django_db
    def test_pair_is_unique(self):
        membership = _active_membership(1)
        role = _tenant_scoped_role(1, "front_desk")
        MembershipRole.objects.create(membership=membership, role=role, tenant_id=1)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                MembershipRole.objects.create(membership=membership, role=role, tenant_id=1)

    @pytest.mark.django_db
    def test_deleting_the_membership_cascades_its_role_grants(self):
        membership = _active_membership(1)
        role = _tenant_scoped_role(1, "front_desk")
        MembershipRole.objects.create(membership=membership, role=role, tenant_id=1)

        membership.delete()

        assert MembershipRole.objects.count() == 0

    @pytest.mark.django_db
    def test_a_referenced_role_cannot_be_deleted(self):
        membership = _active_membership(1)
        role = _tenant_scoped_role(1, "front_desk")
        MembershipRole.objects.create(membership=membership, role=role, tenant_id=1)

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                role.delete()


class TestHasPermission:
    @pytest.mark.django_db
    def test_true_when_a_role_carries_the_code(self):
        membership = _active_membership(1)
        role = _tenant_scoped_role(1, "front_desk")
        RolePermission.objects.create(role=role, tenant_id=1, permission_code="member.view")
        MembershipRole.objects.create(membership=membership, role=role, tenant_id=1)

        assert membership.has_permission("member.view")

    @pytest.mark.django_db
    def test_false_when_no_role_carries_the_code(self):
        membership = _active_membership(1)
        role = _tenant_scoped_role(1, "front_desk")
        RolePermission.objects.create(role=role, tenant_id=1, permission_code="member.view")
        MembershipRole.objects.create(membership=membership, role=role, tenant_id=1)

        assert not membership.has_permission("role.manage")

    @pytest.mark.django_db
    def test_false_for_a_roleless_membership(self):
        membership = _active_membership(1)

        assert not membership.has_permission("member.view")

    @pytest.mark.django_db
    def test_false_for_an_unknown_code(self):
        # Unknown codes fail closed, even if a role could carry them.
        assert not _active_membership(1).has_permission("member.invite_everyone")
