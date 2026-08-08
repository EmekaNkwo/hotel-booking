from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Identity & Access bounded context (DMS §1)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Identity & Access"
