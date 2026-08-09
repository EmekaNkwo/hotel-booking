"""Tenant provisioning (FR-TEN-01, SDD §13.4, T11 composite transaction).

``provision`` is the platform's first composite transaction: tenant + settings
+ feature flags + seeded roles + owner membership + owner role grant, created
in ONE atomic step so onboarding either fully lands or fully rolls back. It is
idempotent by tenant ``code`` — re-provisioning an existing tenant is a no-op
that returns it unchanged (a caller that lost its response can safely retry).
"""

from django.db import transaction

from apps.accounts.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    RolePermission,
    RoleStatus,
    UserAccount,
)
from apps.accounts.permissions import SEEDED_ROLES
from apps.tenants.flags import DEFAULT_ENABLED_FLAGS, FEATURE_FLAG_REGISTRY
from apps.tenants.models import FeatureFlag, Tenant, TenantSettings, TenantStatus


class TenantService:
    @staticmethod
    def provision(
        *,
        code: str,
        name: str,
        base_currency: str,
        owner_email: str,
        default_settings: dict | None = None,
    ) -> Tenant:
        """Create a tenant and its full default footprint in ONE transaction.

        Idempotent by ``code`` (FR-TEN-01): a tenant that already exists is
        returned as-is — nothing is duplicated. The owner account is linked if
        it already exists, otherwise created without a usable password (set via
        the password-reset flow); the owner membership is activated and granted
        the seeded ``tenant_owner`` role.
        """
        with transaction.atomic():
            tenant, created = Tenant.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "base_currency": base_currency,
                    "status": TenantStatus.ACTIVE,
                },
            )
            if not created:
                return tenant

            TenantSettings.objects.create(tenant=tenant, settings=default_settings or {})

            for flag_key in FEATURE_FLAG_REGISTRY:
                FeatureFlag.objects.create(
                    tenant_id=tenant.pk,
                    flag_key=flag_key,
                    enabled=flag_key in DEFAULT_ENABLED_FLAGS,
                )

            roles = {}
            for role_name, permission_codes in SEEDED_ROLES.items():
                role = Role.objects.create(
                    tenant_id=tenant.pk, name=role_name, status=RoleStatus.PUBLISHED
                )
                RolePermission.objects.bulk_create(
                    RolePermission(
                        role=role, tenant_id=tenant.pk, permission_code=code
                    )
                    for code in permission_codes
                )
                roles[role_name] = role

            owner, _ = UserAccount.objects.get_or_create(email=owner_email.lower())
            membership, _ = Membership.objects.unscoped().get_or_create(
                tenant_id=tenant.pk,
                user_account=owner,
                defaults={"status": MembershipStatus.ACTIVE},
            )
            MembershipRole.objects.unscoped().get_or_create(
                membership=membership,
                role=roles["tenant_owner"],
                defaults={"tenant_id": tenant.pk},
            )

        return tenant
