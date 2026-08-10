"""DRF permission classes — RBAC-as-data enforcement (SDD §14.2, §7).

Authorization lives **in the service layer**; the permission class gates access
to the view and is the enforcement of *which roles may call which endpoint*.

Tenant decisions live in the middleware, not in these classes — by the time a
view runs, ``request.tenant_id`` has already been resolved by the principal's
active memberships (never by the payload).

``HasPermission(code)`` is a **factory** — it returns a permission *class*
(not an instance), because DRF instantiates every entry in
``permission_classes`` once per request.
"""

from rest_framework.permissions import BasePermission

from apps.accounts.models import MembershipStatus


class HasTenantContext(BasePermission):
    """Deny unless the request carries a resolved tenant context.

    Multi-membership users without an ``X-Tenant-Id`` header get 403, not a
    mysterious empty result set — a deliberate failure mode that forces the
    client to select a tenant.
    """

    def has_permission(self, request, view):
        return hasattr(request, "tenant_id")


def HasPermission(permission_code: str):
    """Factory: returns a permission class checking a single RBAC code.

    Used on viewsets via ``permission_classes = [..., HasPermission("role.view")]``.
    The membership is cached per-request to avoid N+1 across action checks.
    """

    class _HasPermission(BasePermission):
        def has_permission(self, request, view):
            if not hasattr(request, "tenant_id"):
                return False
            membership = self._get_active_membership(request)
            if membership is None:
                return False
            return membership.has_permission(permission_code)

        def _get_active_membership(self, request):
            cache_key = "_active_membership"
            if hasattr(request, cache_key):
                return getattr(request, cache_key)
            from apps.accounts.models import Membership

            membership = (
                Membership.objects.unscoped()
                .for_user(request.user)
                .filter(tenant_id=request.tenant_id, status=MembershipStatus.ACTIVE)
                .first()
            )
            setattr(request, cache_key, membership)
            return membership

    _HasPermission.__name__ = f"HasPermission[{permission_code}]"
    _HasPermission.__qualname__ = f"HasPermission[{permission_code}]"
    _HasPermission.__doc__ = f"Allow only members carrying {permission_code!r}."
    return _HasPermission
