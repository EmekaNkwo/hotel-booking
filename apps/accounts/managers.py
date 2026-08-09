"""Managers for the accounts bounded context (DMS §1).

``UserAccountManager`` is the custom-user manager: it creates users keyed on
email (the ``USERNAME_FIELD``), normalizes to lowercase so platform-global
uniqueness (DMS invariant #1) is stable at the application layer until the
CITEXT column arrives with the Postgres integration tier.
"""

from django.contrib.auth.base_user import BaseUserManager


class UserAccountManager(BaseUserManager):
    """Manager for ``UserAccount`` — email is the identifier.

    Email is normalized to lowercase before storage: two spellings of the same
    inbox must not create two accounts (DMS invariant #1). The DB unique
    constraint is the backstop; normalization makes the common path correct.
    """

    use_in_migrations = True

    def _create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("UserAccount requires an email address")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email):
        # Mirror the storage normalization so authenticate() matches regardless
        # of the case the caller types (DMS invariant #1).
        return self.get(
            **{self.model.USERNAME_FIELD: self.normalize_email(email).lower()}
        )
