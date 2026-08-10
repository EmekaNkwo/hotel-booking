"""Root URLconf — the project's request routing table.

Django discovers this module through the ``ROOT_URLCONF`` setting. Every
request that survives the middleware chain ends up here: ``URLResolver`` walks
``urlpatterns`` top-down and dispatches to the first matching route.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    # --- M2.3: the first real API surface ---
    path("api/", include("apps.accounts.api.urls")),
    # --- OpenAPI schema + browsable docs (drf-spectacular) ---
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
