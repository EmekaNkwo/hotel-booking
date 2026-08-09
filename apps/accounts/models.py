"""Identity & Access models (DMS §1).

``UserAccount`` is the platform-global principal (E1, FR-AUTH-01): it carries
no ``tenant_id`` because one human may hold memberships in many tenants. It is
built from ``AbstractBaseUser`` + ``PermissionsMixin`` — email login, no
username column. ``Membership`` is the user ↔ tenant grant whose lifecycle
(pending → active → revoked) the invitation flow (M2.2) and the tenant
principal plumbing (M2.1) both consume.
"""

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from apps.accounts.managers import UserAccountManager
from apps.shared.models import (
    TenantScopedMixin,
    TimeStampedMixin,
    VersionedMixin,
)
from apps.shared.models.recipes import partial_index, status_constraint
from apps.shared.tenancy import TenantScopedManager, TenantScopedQuerySet


class UserStatus(models.TextChoices):
    """Lifecycle of a user account (DDS §1) — locked is retryable, deactivated terminal."""

    ACTIVE = "active", "Active"
    LOCKED = "locked", "Locked"
    DEACTIVATED = "deactivated", "Deactivated"


class UserAccount(AbstractBaseUser, PermissionsMixin, TimeStampedMixin, VersionedMixin):
    """Platform-global account who can authenticate (no tenant_id).

    Email is the username (``USERNAME_FIELD``), unique platform-wide (DMS
    invariant #1). ``is_active`` is derived from ``status`` so Django's auth
    backends honor the same state machine the rest of the platform sees —
    a locked or deactivated account cannot authenticate, with one switch.
    """

    email = models.EmailField(max_length=254, unique=True)
    is_staff = models.BooleanField(
        default=False, help_text="May access the platform admin site."
    )
    status = models.CharField(
        max_length=20,
        choices=UserStatus.choices,
        default=UserStatus.ACTIVE,
    )
    failed_attempts = models.PositiveSmallIntegerField(default=0, editable=False)
    deactivated_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = UserAccountManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "user_account"
        verbose_name = "user account"
        verbose_name_plural = "user accounts"
        constraints = [
            status_constraint("status", UserStatus, "user_account_status_valid"),
            models.CheckConstraint(
                condition=models.Q(failed_attempts__gte=0),
                name="user_account_failed_attempts_ge_zero",
            ),
        ]
        indexes = [
            partial_index(
                fields=["status"],
                condition=~models.Q(status=UserStatus.DEACTIVATED),
                name="user_account_ix_active_status",
            ),
            models.Index(fields=["created_at"], name="user_account_ix_created"),
        ]

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    def __str__(self) -> str:
        return self.email


class MembershipStatus(models.TextChoices):
    """Lifecycle of a user↔tenant grant (DDS §1)."""

    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class MembershipQuerySet(TenantScopedQuerySet):
    """Membership lookups: by user, tenant, and active state.

    ``active`` (from the base) filters ``status='active'`` — exactly the grant
    the principal plumbing validates against.
    """

    def for_user(self, user) -> "MembershipQuerySet":
        return self.filter(user_account_id=user.pk)


class MembershipManager(TenantScopedManager):
    queryset_class = MembershipQuerySet

    def for_user(self, user) -> MembershipQuerySet:
        # Explicit: a user's memberships are looked up before a tenant context
        # exists (and must never be auto-filtered to some other tenant).
        return self.unscoped().for_user(user)


class Membership(TimeStampedMixin, VersionedMixin, TenantScopedMixin):
    """The fact "user X belongs to tenant T."

    ``status='active'`` is the grant; the partial unique index guarantees at
    most one active grant per (tenant, user) — you cannot be granted twice to
    the same tenant while the first grant is live (DMS invariant #6).
    """

    user_account = models.ForeignKey(
        UserAccount,
        on_delete=models.RESTRICT,
        related_name="memberships",
    )
    status = models.CharField(
        max_length=20,
        choices=MembershipStatus.choices,
        default=MembershipStatus.PENDING,
    )
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = MembershipManager()

    class Meta:
        db_table = "membership"
        constraints = [
            status_constraint("status", MembershipStatus, "membership_status_valid"),
            models.UniqueConstraint(
                fields=["tenant_id", "user_account_id"],
                condition=models.Q(status=MembershipStatus.ACTIVE),
                name="membership_uq_tenant_user",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user_account_id", "status"],
                name="membership_ix_user_status",
            ),
            models.Index(
                fields=["tenant_id", "status"],
                name="membership_ix_tenant_status",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_account_id} @ tenant {self.tenant_id}"
