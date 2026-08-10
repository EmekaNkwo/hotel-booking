"""Tenant context + application-layer tenant scoping (DR-01, SDD §13.2 layer 2).

Two mechanisms live here:

1. **Request tenant context** — a thread-local holder set once by
   ``TenantContextMiddleware`` after it validates the principal's membership.
   ``require_current_tenant()`` is the loud failure mode: business code that
   must run inside a tenant calls it and gets an exception instead of silently
   running an unfiltered query. The thread-local is cleared on every request
   exit (even exceptions), so a context can never leak onto another request.

2. **Tenant-scoped QuerySet/Manager base** — every tenant-scoped model
   inherits this. ``get_queryset()`` auto-filters by the request tenant when
   one is set (defense-in-depth: a developer who forgets an explicit filter is
   still scoped), and is deliberately *unfiltered* when no context exists so
   that cross-tenant work (platform admin, maintenance) is an explicit
   ``.unscoped()`` act — never implicit.

The database-level backstop (RLS) and the transaction-local
``set_config('app.tenant_id', …, true)`` stamp are layered in the middleware
and the RLS migrations (SDD §13.2 layers 1 and 3).
"""

import threading
from contextlib import contextmanager

from django.db import connection, models

from apps.shared.exceptions import TenantContextMissing

_thread_local = threading.local()


# ---------------------------------------------------------------------------
# Request tenant context
# ---------------------------------------------------------------------------

def current_tenant_id() -> int | None:
    """The tenant stamped for the current request/thread, or None."""
    return getattr(_thread_local, "tenant_id", None)


def require_current_tenant() -> int:
    """Return the current tenant or raise — never run scoped queries without one."""
    tenant_id = current_tenant_id()
    if tenant_id is None:
        raise TenantContextMissing(
            "no tenant context on this thread; queries must be explicitly "
            "scoped or run inside a tenant-authenticated request"
        )
    return tenant_id


def set_request_tenant(tenant_id: int) -> None:
    """Stamp the validated tenant for the current thread (middleware only)."""
    _thread_local.tenant_id = tenant_id


def clear_request_tenant() -> None:
    """Drop the thread-local context. Called on every request exit, including
    exceptions, so a context cannot leak into the next request."""
    _thread_local.tenant_id = None


@contextmanager
def run_as_tenant(tenant_id: int):
    """Stamp tenant context for a non-request code path (trusted services).

    Mirrors exactly what ``TenantContextMiddleware`` does for a request — the
    thread-local (app-layer scoping) AND the transaction-local
    ``set_config('app.tenant_id', …, true)`` that RLS reads — so trusted
    service code that runs WITHOUT a resolved membership can still write
    tenant-scoped rows under the correct context and RLS admits them.

    This is the second trusted stamping path. It exists ONLY where the
    authorization is not a membership the middleware could have resolved:

    - invitation redemption — the token IS the authorization;
    - tenant provisioning — the brand-new tenant has no members yet;
    - maintenance sweeps (e.g. invitation expiry) that touch many tenants.

    It is deliberately NOT for request code (the middleware owns that) and not
    a way to bypass app-layer scoping: the thread-local is restored on exit,
    and the DB GUC is transaction-local so it is auto-discarded at commit or
    rollback.
    """
    previous = current_tenant_id()
    set_request_tenant(tenant_id)
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)", [str(tenant_id)]
            )
    try:
        yield
    finally:
        clear_request_tenant()
        if previous is not None:
            set_request_tenant(previous)


# ---------------------------------------------------------------------------
# Tenant-scoped QuerySet / Manager base
# ---------------------------------------------------------------------------

class TenantScopedQuerySet(models.QuerySet):
    """Base queryset for tenant-scoped models.

    ``for_tenant`` is the explicit scope; ``active`` is a convenience for the
    common ``status = 'active'`` state. Models whose "active" predicate differs
    override ``active``.
    """

    def for_tenant(self, tenant_id: int) -> "TenantScopedQuerySet":
        return self.filter(tenant_id=tenant_id)

    def active(self) -> "TenantScopedQuerySet":
        return self.filter(status="active")


class TenantScopedManager(models.Manager):
    """Manager that auto-filters by the request tenant when one is set.

    ``get_queryset()`` applies ``current_tenant_id()`` when present — the
    application-level backstop that catches a forgotten explicit filter. When
    no context exists the queryset is unfiltered (cross-tenant platform work
    must be explicit via ``.unscoped()``). Manager-level ``for_tenant`` goes
    through ``unscoped`` so an explicit scope is never silently ANDed with a
    request tenant that would empty it.
    """

    queryset_class = TenantScopedQuerySet

    def get_queryset(self) -> TenantScopedQuerySet:
        qs = self.queryset_class(self.model, using=self._db)
        tenant_id = current_tenant_id()
        if tenant_id is not None:
            qs = qs.for_tenant(tenant_id)
        return qs

    def unscoped(self) -> TenantScopedQuerySet:
        """Deliberate cross-tenant access (platform admin, maintenance jobs)."""
        return self.queryset_class(self.model, using=self._db)

    def for_tenant(self, tenant_id: int) -> TenantScopedQuerySet:
        return self.unscoped().for_tenant(tenant_id)
