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

from apps.accounts.models import Membership
from apps.shared import tenancy


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
