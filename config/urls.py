"""Root URLconf — the project's request routing table.

Django discovers this module through the ``ROOT_URLCONF`` setting. Every
request that survives the middleware chain ends up here: ``URLResolver`` walks
``urlpatterns`` top-down and dispatches to the first matching route.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    # --- M2.3: the first real API surface ---
    path("api/", include("apps.accounts.api.urls")),
    # --- A0: thin HTTP surface over the M6-M13 service/query layers ---
    # (apps.properties.api added in A2 — see its module docstring: A0 never
    # exposed a Property list, leaving availability search unusable from
    # the UI with no way to discover a property_id.)
    path("api/", include("apps.properties.api.urls")),
    path("api/", include("apps.rooms.api.urls")),
    path("api/", include("apps.guests.api.urls")),
    path("api/", include("apps.availability.api.urls")),
    path("api/", include("apps.reservations.api.urls")),
    path("api/", include("apps.bookings.api.urls")),
    path("api/", include("apps.allocation.api.urls")),
    path("api/", include("apps.housekeeping.api.urls")),
    path("api/", include("apps.notifications.api.urls")),
    # --- OpenAPI schema + browsable docs (drf-spectacular) ---
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

# R1.2: config/settings/dev.py enables DebugToolbarMiddleware whenever
# DEBUG is on, but the middleware also needs its own URLconf mounted (the
# toolbar's panels fetch their content over AJAX from "__debug__/") — that
# was missing, so it 500'd on every request in dev (NoReverseMatch:
# 'djdt' is not a registered namespace). Gated on settings.DEBUG (never
# true outside dev.py — see base.py's `DEBUG = env.bool(..., default=False)`
# and test.py/integration.py/prod.py's explicit `DEBUG = False`), so this
# is a no-op import/route everywhere except real local development; no
# other settings module's URL surface changes.
if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
