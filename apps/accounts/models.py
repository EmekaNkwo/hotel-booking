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
from django.db import connection, models

from apps.accounts.managers import UserAccountManager
from apps.accounts.permissions import is_valid
from apps.shared.models import (
    TenantScopedMixin,
    TimeStampedMixin,
    VersionedMixin,
)
from apps.shared.models.recipes import partial_index, status_constraint
from apps.shared.tenancy import TenantScopedManager, TenantScopedQuerySet
from apps.tenants.models import Tenant, TenantStatus


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
    locked_at = models.DateTimeField(null=True, blank=True, editable=False)
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

    def principal_tenants(self, user) -> list[int]:
        """The user's active tenants, resolved WITHOUT a tenant context.

        This is the middleware's principal lookup — the ONE read that must see
        memberships across all tenants before any context exists. Under RLS
        FORCE that read would be scoped to the empty config and return nothing,
        so Postgres routes it through the ``SECURITY DEFINER`` function
        ``app.active_memberships``: the single sanctioned cross-tenant read,
        which also excludes non-active (suspended/decommissioned) tenants.
        SQLite has no RLS, so it falls back to the equivalent ORM query so the
        unit tier exercises the same contract.
        """
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT app.active_memberships(%s)", [user.pk])
                return [row[0] for row in cursor.fetchall()]

        ids = list(
            self.unscoped()
            .for_user(user)
            .filter(status=MembershipStatus.ACTIVE)
            .values_list("tenant_id", flat=True)
        )
        if not ids:
            return []
        return list(
            Tenant.objects.filter(pk__in=ids, status=TenantStatus.ACTIVE).values_list(
                "pk", flat=True
            )
        )


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

    def has_permission(self, permission_code: str) -> bool:
        """RBAC-as-data authorization check (SDD §7.2, §14.2 chain step 3).

        True when one of this membership's roles carries ``permission_code``.
        Unknown codes fail closed. The read joins membership_role → role →
        role_permission; the join tables denormalize the membership's own
        tenant_id, so the authorization read stays inside the tenant even
        before RLS lands.
        """
        if not is_valid(permission_code):
            return False
        return self.roles.filter(
            role__permissions__permission_code=permission_code
        ).exists()

    def __str__(self) -> str:
        return f"{self.user_account_id} @ tenant {self.tenant_id}"


class RoleStatus(models.TextChoices):
    """Lifecycle of a tenant-scoped role (DDS §1).

    ``retired`` is the soft delete: memberships keep the role reference, so a
    retired role is never deleted out from under a grant.
    """

    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"


class Role(TenantScopedMixin, VersionedMixin, TimeStampedMixin):
    """A named, tenant-scoped permission set (RBAC as data, DDS §1).

    Versioned so permission changes are auditable; ``retired`` (never deleted)
    so memberships referencing the role stay valid.
    """

    name = models.CharField(max_length=60)
    status = models.CharField(
        max_length=20, choices=RoleStatus.choices, default=RoleStatus.DRAFT
    )

    objects = TenantScopedManager()

    class Meta:
        db_table = "role"
        constraints = [
            status_constraint("status", RoleStatus, "role_status_valid"),
            models.UniqueConstraint(
                fields=["tenant_id", "name"], name="role_uq_tenant_name"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="role_ix_tenant_status")
        ]

    def __str__(self) -> str:
        return self.name


class RolePermission(TenantScopedMixin):
    """role → permission code (RBAC as data, DDS §1).

    CASCADE: a permission row is genuinely part of the role's life (DDS A.3) —
    a role that is deleted takes its permission set with it. ``tenant_id`` is
    denormalized onto the join for RLS (DDS A.2: every row carries its own
    tenant_id).

    DDS spec: composite PK ``(role_id, permission_code)``; implemented here as
    a surrogate id + unique constraint (consistent with every table in the
    platform; the invariant is identical).
    """

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    permission_code = models.CharField(max_length=80)

    objects = TenantScopedManager()

    class Meta:
        db_table = "role_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission_code"], name="role_permission_uq_role_code"
            )
        ]
        indexes = [
            models.Index(fields=["permission_code"], name="role_permission_ix_code")
        ]

    def __str__(self) -> str:
        return f"{self.role_id} -> {self.permission_code}"


class MembershipRole(TenantScopedMixin):
    """membership → roles (DDS §1): the role grants a membership holds.

    CASCADE from membership (the grant is part of the membership's life);
    RESTRICT from role (a role is retired, never deleted, while referenced).
    """

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="roles"
    )
    role = models.ForeignKey(Role, on_delete=models.RESTRICT, related_name="memberships")

    objects = TenantScopedManager()

    class Meta:
        db_table = "membership_role"
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "role"], name="membership_role_uq_pair"
            )
        ]

    def __str__(self) -> str:
        return f"membership {self.membership_id} -> role {self.role_id}"


class InvitationStatus(models.TextChoices):
    """Lifecycle of a pending invite (DDS §1)."""

    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    EXPIRED = "expired", "Expired"
    REVOKED = "revoked", "Revoked"


class InvitationManager(TenantScopedManager):
    """Invitation lookups; the token-hash pre-context lookup is vendor-gated."""

    def lookup_tenant_by_token_hash(self, token_hash: str) -> int | None:
        """The invitation's tenant from its token hash, WITHOUT a tenant context.

        Redemption runs before the invitee has any membership, so it must read
        the invitation across tenants by token (the token IS the
        authorization). Under RLS FORCE that read would fail closed, so
        Postgres routes it through the ``SECURITY DEFINER`` function
        ``app.invitation_tenant``; SQLite falls back to the ORM. Returns None
        when no invitation holds the hash — the caller maps that to
        ``InvitationNotFound``.
        """
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT app.invitation_tenant(%s)", [token_hash])
                row = cursor.fetchone()
                return row[0] if row else None
        return (
            self.unscoped()
            .filter(token_hash=token_hash)
            .values_list("tenant_id", flat=True)
            .first()
        )


class Invitation(TenantScopedMixin, VersionedMixin, TimeStampedMixin):
    """A pending invite to join a tenant (DDS §1).

    The raw token is returned to the inviter exactly once, at creation, and
    stored only as ``token_hash`` (sha256) — the database never holds the
    secret. The redemption flow (MembershipService) looks the invitation up by
    token_hash and applies its status/expiry/email guards inside
    ``select_for_update``. The invitee has no membership yet, so redemption
    reads the invitation unscoped by token (the token is the authorization) —
    which is also why this table is deferred from the RLS expansion.
    """

    email = models.EmailField(max_length=254)
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=20,
        choices=InvitationStatus.choices,
        default=InvitationStatus.PENDING,
    )
    expires_at = models.DateTimeField()
    invited_by = models.ForeignKey(
        UserAccount,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invitations_sent",
    )
    role = models.ForeignKey(
        Role,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invitations",
    )

    objects = InvitationManager()

    class Meta:
        db_table = "invitation"
        constraints = [
            status_constraint("status", InvitationStatus, "invitation_status_valid"),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="invitation_expiry_after_created",
            ),
        ]
        indexes = [
            partial_index(
                fields=["tenant_id", "status", "expires_at"],
                condition=models.Q(status=InvitationStatus.PENDING),
                name="invitation_pending_tenant_exp",
            )
        ]

    def __str__(self) -> str:
        return f"invite {self.email} @ tenant {self.tenant_id} ({self.status})"
