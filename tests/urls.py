"""Test-only URLconf — exercises the middleware against a real request.

Prod routing stays in ``config/urls.py``; tests that need a live request (the
tenant-context middleware tests) override ``ROOT_URLCONF`` to this module so
prod routes are never polluted with test-support endpoints.
"""

from django.http import JsonResponse
from django.urls import path

from apps.shared import tenancy


def tenant_echo(request):
    """Echo what the middleware stamped on the request and thread."""
    return JsonResponse(
        {
            "user": request.user.email if request.user.is_authenticated else None,
            "request_tenant_id": getattr(request, "tenant_id", None),
            "thread_tenant_id": tenancy.current_tenant_id(),
        }
    )


urlpatterns = [
    path("echo/", tenant_echo),
]
