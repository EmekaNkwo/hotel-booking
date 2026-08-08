from django.apps import AppConfig


class SharedConfig(AppConfig):
    """Shared Kernel (DMS §21). The only app with no dependencies."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shared"
    label = "shared"
    verbose_name = "Shared Kernel"
