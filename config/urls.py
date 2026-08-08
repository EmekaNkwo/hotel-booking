"""Root URLconf — the project's request routing table.

Django discovers this module through the ``ROOT_URLCONF`` setting. Every
request that survives the middleware chain ends up here: ``URLResolver`` walks
``urlpatterns`` top-down and dispatches to the first matching route.
"""

from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Per-context API routes mount here as each milestone ships them.
    # Example (M2): path("api/", include("apps.accounts.urls")),
]
