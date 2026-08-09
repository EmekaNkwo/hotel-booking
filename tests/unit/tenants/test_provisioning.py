"""Unit tests for tenant provisioning (M2.2, FR-TEN-01, T11 composite).

Order: happy-path footprint → idempotency → composite atomicity → edge cases.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Membership, MembershipRole, Role, RoleStatus
from apps.accounts.permissions import PERMISSION_CODES, SEEDED_ROLES
from apps.tenants.flags import DEFAULT_ENABLED_FLAGS, FEATURE_FLAG_REGISTRY
from apps.tenants.models import FeatureFlag, Tenant, TenantSettings
from apps.tenants.services import TenantService

TENANT = {
    "code": "acme",
    "name": "Acme Hotels",
    "base_currency": "NGN",
    "owner_email": "owner@acme.example",
}


class TestHappyPath:
    @pytest.mark.django_db
    def test_returns_an_active_tenant(self):
        tenant = TenantService.provision(**TENANT)

        assert tenant.code == "acme"
        assert tenant.status == "active"
        assert tenant.base_currency == "NGN"

    @pytest.mark.django_db
    def test_creates_one_settings_row(self):
        tenant = TenantService.provision(**TENANT)

        assert TenantSettings.objects.filter(tenant=tenant).count() == 1

    @pytest.mark.django_db
    def test_seeds_every_registry_flag_with_the_default_enablement(self):
        TenantService.provision(**TENANT)

        flags = {f.flag_key: f.enabled for f in FeatureFlag.objects.all()}
        assert set(flags) == set(FEATURE_FLAG_REGISTRY)
        for key, enabled in flags.items():
            assert enabled == (key in DEFAULT_ENABLED_FLAGS)

    @pytest.mark.django_db
    def test_seeds_the_default_roles_published_with_their_permissions(self):
        TenantService.provision(**TENANT)

        roles = Role.objects.filter(tenant_id=Tenant.objects.get().pk)
        assert {r.name for r in roles} == set(SEEDED_ROLES)
        for role in roles:
            assert role.status == RoleStatus.PUBLISHED
            codes = set(role.permissions.values_list("permission_code", flat=True))
            assert codes == SEEDED_ROLES[role.name]

    @pytest.mark.django_db
    def test_activates_the_owner_membership_with_the_owner_role(self):
        tenant = TenantService.provision(**TENANT)

        owner = tenant  # the tenant's pk is the membership tenant
        membership = Membership.objects.get(tenant_id=owner.pk)
        assert membership.user_account.email == "owner@acme.example"
        assert membership.status == "active"
        assert membership.roles.get().role.name == "tenant_owner"

    @pytest.mark.django_db
    def test_owner_membership_can_act_with_a_permission(self):
        TenantService.provision(**TENANT)

        membership = Membership.objects.get(tenant_id=Tenant.objects.get().pk)
        assert membership.has_permission("member.invite")
        assert membership.has_permission("tenant.manage")


class TestIdempotency:
    @pytest.mark.django_db
    def test_reprovision_returns_the_same_tenant(self):
        first = TenantService.provision(**TENANT)
        second = TenantService.provision(**TENANT)

        assert second.pk == first.pk

    @pytest.mark.django_db
    def test_reprovision_duplicates_nothing(self):
        TenantService.provision(**TENANT)
        TenantService.provision(**TENANT)

        assert Tenant.objects.count() == 1
        assert TenantSettings.objects.count() == 1
        assert FeatureFlag.objects.count() == len(FEATURE_FLAG_REGISTRY)
        assert Role.objects.count() == len(SEEDED_ROLES)
        assert Membership.objects.count() == 1
        assert MembershipRole.objects.count() == 1


class TestCompositeAtomicity:
    @pytest.mark.django_db
    def test_a_failed_step_rolls_back_the_whole_provision(self):
        # base_currency fails the ISO-3 CHECK — nothing may survive.
        bad = dict(TENANT, base_currency="naira")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                TenantService.provision(**bad)

        assert Tenant.objects.count() == 0
        assert TenantSettings.objects.count() == 0
        assert FeatureFlag.objects.count() == 0
        assert Role.objects.count() == 0
        assert Membership.objects.count() == 0


class TestEdgeCases:
    @pytest.mark.django_db
    def test_existing_owner_account_is_linked_not_duplicated(self):
        from django.contrib.auth import get_user_model

        get_user_model().objects.create_user(email="owner@acme.example")

        TenantService.provision(**TENANT)

        assert get_user_model().objects.count() == 1

    @pytest.mark.django_db
    def test_permission_registry_and_seeds_agree(self):
        # Every seeded code must be in the registry (no freeform strings).
        for codes in SEEDED_ROLES.values():
            assert codes <= PERMISSION_CODES
