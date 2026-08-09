from django.apps import AppConfig


class TenantsConfig(AppConfig):
    """Tenancy bounded context (DMS §2) — the platform-scoped tenant root."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenants"
    label = "tenants"
    verbose_name = "Tenancy"
