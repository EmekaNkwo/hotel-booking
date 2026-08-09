"""Permission-code registry for RBAC-as-data (SDD §7, DDS §1 role_permission).

``role_permission`` rows are data, but the codes they may carry are a closed
set — no freeform strings (the DB cannot CHECK against a registry, so this
module is the app-layer validation backstop). Codes follow SDD §7.2's scoping
dimensions at tenant scope; property-scoped codes arrive with the property
model (M3+). ``SEEDED_ROLES`` is the source of the default roles created by
``TenantService.provision``.
"""

from __future__ import annotations


class Permissions:
    """Every valid permission code at M2 (tenant scope only)."""

    TENANT_VIEW = "tenant.view"
    TENANT_MANAGE = "tenant.manage"
    MEMBER_VIEW = "member.view"
    MEMBER_INVITE = "member.invite"
    MEMBER_MANAGE = "member.manage"
    ROLE_VIEW = "role.view"
    ROLE_MANAGE = "role.manage"
    SETTINGS_VIEW = "settings.view"
    SETTINGS_MANAGE = "settings.manage"
    FEATURE_FLAG_MANAGE = "feature_flag.manage"


def _codes_from(cls) -> frozenset[str]:
    return frozenset(
        value
        for value in vars(cls).values()
        if isinstance(value, str) and value.count(".") == 1
    )


PERMISSION_CODES: frozenset[str] = _codes_from(Permissions)


def is_valid(code: str) -> bool:
    """Validate a stored/derived permission code against the registry."""
    return code in PERMISSION_CODES


# The default role set created at provisioning. M2 seeds only the tenant-scoped
# owner role; property-scoped roles (property_manager, front_desk, …) are
# seeded with the property model in M3.
SEEDED_ROLES: dict[str, frozenset[str]] = {
    "tenant_owner": PERMISSION_CODES,
}
