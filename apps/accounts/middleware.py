"""Tenant principal resolution — the request-scoped security cross-cut (M2.1).

This middleware is the spine the M1 WorkflowRunner's ``actor`` and the RLS
policies hang off. It runs after AuthenticationMiddleware (needs
``request.user``) and before any app code that queries tenant-scoped data, and
it does three things once per request (SDD §13.2 layer 1):

1. **Wrap the whole request in one transaction.** ``set_config(..., true)`` is
   transaction-local, so it must be set inside a transaction that covers every
   query of the request. Wrapping here — rather than relying on
   ``ATOMIC_REQUESTS``, which only wraps the view callback — guarantees the
   config is stable for the whole request and is *automatically discarded when
   the transaction ends*. That discard is what makes a pooled/reused
   connection unable to leak tenant A into tenant B's next request.

2. **Derive the effective tenant from the principal, never the payload.**
   The validated facts are: the authenticated user + their active memberships.
   A client ``X-Tenant-Id`` header is honored ONLY when it matches one of the
   user's active memberships; otherwise ``PermissionDenied``. A single active
   membership auto-selects; multiple memberships with no selection establish
   no implicit context (business code then must scope explicitly).

3. **Stamp both layers**: the thread-local context (``tenancy``) that the
   app-layer tenant-scoped managers read, and the DB-level
   ``set_config('app.tenant_id', …)`` that RLS reads. ``set_config`` is a
   no-op on non-Postgres (SQLite unit tier).
"""

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction

from apps.accounts.models import Membership, MembershipStatus
from apps.accounts.services import MFA_REQUIRED_ROLES
from apps.shared import tenancy

#: Endpoints the authenticated user must always reach even while an
#: MFA-required role is not yet satisfied: the auth identity surface (so a
#: client can discover and leave) and the MFA device lifecycle (so an owner
#: can enroll/verify/remove devices to satisfy the requirement — the
#: chicken-and-egg break). ``/api/auth/login/`` and ``/api/auth/mfa/`` are
#: pre-auth (anonymous), so they are skipped by the authenticated check anyway;
#: listing them here makes the boundary explicit.
MFA_EXEMPT_PREFIXES = (
    "/api/auth/login/",
    "/api/auth/mfa/",
    "/api/auth/logout/",
    "/api/auth/me/",
    "/api/mfa/devices/",
)


def _membership_requires_mfa(user, tenant_id: int) -> bool:
    """True when the user's ACTIVE membership in ``tenant_id`` carries an
    MFA-required role (SDD §14.1; ``MFA_REQUIRED_ROLES`` is the single source
    of truth — never duplicated). Scoped to the EFFECTIVE tenant, so the
    policy is tenant-sensitive: completing MFA never makes a tenant where the
    user merely holds a non-required role count as satisfied.
    """
    from django.conf import settings

    if getattr(settings, "MFA_ENFORCEMENT_DISABLED", False):
        return False
    return Membership.objects.unscoped().filter(
        tenant_id=tenant_id,
        user_account=user,
        status=MembershipStatus.ACTIVE,
        roles__role__name__in=MFA_REQUIRED_ROLES,
    ).exists()


class TenantContextMiddleware:
    """Resolve and stamp the request's tenant context (SDD §13.2 layer 1)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with transaction.atomic():
            self._establish(request)
            try:
                response = self.get_response(request)
            finally:
                tenancy.clear_request_tenant()
        return response

    # -- resolution ---------------------------------------------------------

    def _establish(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        tenant_id = self._resolve_tenant(request, user)
        if tenant_id is None:
            return
        request.tenant_id = tenant_id
        tenancy.set_request_tenant(tenant_id)
        self._stamp_db(tenant_id)

    def _resolve_tenant(self, request, user) -> int | None:
        # principal_tenants is the ONE sanctioned cross-tenant read: it routes
        # through the SECURITY DEFINER app.active_memberships on Postgres (RLS
        # FORCE would otherwise scope this to the empty config) and excludes
        # memberships in non-active tenants.
        tenant_ids = Membership.objects.principal_tenants(user)
        if not tenant_ids:
            return None

        header = request.headers.get("X-Tenant-Id")
        if header is not None:
            try:
                selected = int(header)
            except ValueError:
                raise PermissionDenied("X-Tenant-Id must be an integer") from None
            if selected not in tenant_ids:
                raise PermissionDenied("not a member of the requested tenant")
            return selected

        if len(tenant_ids) == 1:
            return tenant_ids[0]
        return None  # multiple memberships, no validated selection

    # -- stamping -----------------------------------------------------------

    def _stamp_db(self, tenant_id: int) -> None:
        if connection.vendor != "postgresql":
            return  # SQLite has no set_config; the app layer still scopes.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)]
            )


class MfaEnforcementMiddleware:
    """Enforce the tenant-sensitive MFA boundary (M2.5 step 7).

    Runs AFTER TenantContextMiddleware (needs ``request.tenant_id`` and the
    stamped RLS config — the transaction that wraps this request is the one
    TenantContextMiddleware opened, so ``set_config`` is live here). For an
    authenticated user acting in a tenant where their active membership
    carries an MFA-required role (currently ``tenant_owner``), the session
    must show MFA assurance for THAT tenant, or the request is denied.

    Assurance is ``mfa_verified_tenants`` in the server-side session: the
    active tenants at the moment MFA completed (the Step 6 login flow stamps
    it). It is derived from the principal's own memberships by the login
    flow — never from a client-supplied field — so it cannot be forged or
    copied into another session, and it is evaluated against the EFFECTIVE
    tenant on every request. Consequences of that tenant-sensitivity:

    - A tenant the user was granted AFTER login is not in the stamp, so
      operating there as an MFA-required role demands a fresh MFA login —
      "completed MFA once" does not satisfy every tenant.
    - Revoking the membership or removing the owner role flips
      ``_membership_requires_mfa`` to False for that tenant, so the user is no
      longer blocked (and conversely a promotion to owner now blocks until a
      fresh login).

    The MFA device lifecycle and auth identity endpoints are exempt so an
    owner can enroll/verify devices (the setup chicken-and-egg) and can always
    discover who they are and log out.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._enforce(request)
        return self.get_response(request)

    def _enforce(self, request) -> None:
        user = getattr(request, "user", None)
        tenant_id = getattr(request, "tenant_id", None)
        if user is None or not user.is_authenticated or tenant_id is None:
            return
        if request.path.startswith(MFA_EXEMPT_PREFIXES):
            return
        if not _membership_requires_mfa(user, tenant_id):
            return
        if tenant_id not in (request.session.get("mfa_verified_tenants") or ()):
            # Authenticated but not MFA-satisfied in this tenant. A plain 403 —
            # no WWW-Authenticate, no redirect (this is an API): the client is
            # expected to drive the user through the Step 6 flow.
            raise PermissionDenied("mfa is required to operate in this tenant")
