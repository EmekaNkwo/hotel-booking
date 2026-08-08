from django.contrib.auth.models import AbstractUser


class UserAccount(AbstractUser):
    """Platform-global account — placeholder (Roadmap E1).

    Exists to lock ``AUTH_USER_MODEL = "accounts.UserAccount"`` before the first
    migration. Deliberately the Django default today; replaced in M2 by the real
    identity model (email login, MFA) while the database is still empty.

    ``user_account`` is platform-global — it carries no ``tenant_id``, because
    one human may hold memberships in many tenants (DMS §1).
    """

    class Meta:
        verbose_name = "user account"
        verbose_name_plural = "user accounts"
