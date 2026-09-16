"""Guest Profile models (M5, DDS S16).

Guest is the lifecycle hub — the canonical guest record must exist *before*
any booking (SDD S11.9), resolved by email/phone within a tenant. Profile
changes never rewrite booking history (bookings snapshot guest data).

``GuestProfile``, ``GuestPreference``, and ``IdDocument`` follow the M3
convention: ``EntityMixin`` (timestamps + tenant + optimistic lock) with an
explicit ``tenant`` FK overriding the mixin's bare ``tenant_id``, same as
``Property``/``Building``. ``GuestConsent`` is the one exception: it is a
lawful-basis *log*, so it combines tenant-scoping with ``AppendOnlyMixin``
(no UPDATE/DELETE at the model or queryset layer) instead of optimistic
locking — there is nothing to lock when rows are never mutated.
"""

from django.db import models

from apps.shared.models import AppendOnlyMixin, AppendOnlyQuerySet, EntityMixin
from apps.shared.models.recipes import status_constraint
from apps.shared.tenancy import TenantScopedManager, TenantScopedQuerySet


class GuestStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    MERGED = "merged", "Merged"
    CLOSED = "closed", "Closed"


class ConsentPurpose(models.TextChoices):
    MARKETING = "marketing", "Marketing"
    PROCESSING = "processing", "Processing"


class PreferenceCategory(models.TextChoices):
    ROOM = "room", "Room"
    LANGUAGE = "lang", "Language"
    ACCESSIBILITY = "accessibility", "Accessibility"
    AMENITY = "amenity", "Amenity"


class DocumentStatus(models.TextChoices):
    CURRENT = "current", "Current"
    EXPIRED = "expired", "Expired"
    REMOVED = "removed", "Removed"


class GuestProfile(EntityMixin):
    """Canonical guest record: identity resolution, preferences, consent, history."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="guest_profiles",
    )
    user_account = models.ForeignKey(
        "accounts.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="guest_profiles",
    )
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_profiles",
    )
    # CITEXT on Postgres (guests/migrations/0002_citext_primary_email.py); a
    # plain column on SQLite — case-insensitive matching there comes from the
    # Email VO normalizing to lowercase before it ever reaches the database.
    primary_email = models.CharField(max_length=254, null=True, blank=True)
    primary_phone = models.CharField(max_length=20, null=True, blank=True)
    name = models.JSONField(default=dict, blank=True)  # GuestName.to_dict()
    language = models.CharField(max_length=16, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=GuestStatus.choices,
        default=GuestStatus.ACTIVE,
    )
    erasure_ref = models.CharField(max_length=64, null=True, blank=True)
    erased_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            status_constraint("status", GuestStatus, "guest_profile_valid_status"),
            models.UniqueConstraint(
                fields=["tenant", "primary_email"],
                condition=models.Q(erased_at__isnull=True, merged_into__isnull=True),
                name="guest_profile_uq_tenant_email_active",
            ),
            models.UniqueConstraint(
                fields=["tenant", "primary_phone"],
                condition=models.Q(erased_at__isnull=True, merged_into__isnull=True),
                name="guest_profile_uq_tenant_phone_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "primary_email"]),
            models.Index(fields=["tenant", "primary_phone"]),
            # GIN(name) is Postgres-only and added out-of-band in
            # guests/migrations/0003_gin_index_guest_profile_name.py — GinIndex
            # emits `USING gin` unconditionally and would break the SQLite unit
            # tier if declared here.
        ]

    def __str__(self) -> str:
        return f"guest {self.pk} ({self.status})"


class GuestPreference(EntityMixin):
    """A room/language/accessibility/amenity preference belonging to a profile."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="guest_preferences",
    )
    guest_profile = models.ForeignKey(
        GuestProfile,
        on_delete=models.CASCADE,
        related_name="preferences",
    )
    category = models.CharField(max_length=16, choices=PreferenceCategory.choices)
    value = models.JSONField(default=dict, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            status_constraint(
                "category", PreferenceCategory, "guest_preference_valid_category"
            ),
            models.UniqueConstraint(
                fields=["guest_profile", "category"],
                name="guest_preference_uq_profile_category",
            ),
        ]
        indexes = [
            models.Index(fields=["guest_profile"]),
        ]

    def __str__(self) -> str:
        return f"{self.category} preference for guest {self.guest_profile_id}"


class GuestConsentQuerySet(TenantScopedQuerySet, AppendOnlyQuerySet):
    """Tenant-scoped AND append-only: the read side auto-filters, the write
    side (update/delete) is refused — combining both existing base querysets
    rather than inventing a third mechanism."""


class GuestConsentManager(TenantScopedManager):
    queryset_class = GuestConsentQuerySet


class GuestConsent(AppendOnlyMixin):
    """Append-only lawful-basis history, one row per purpose per event.

    A row is never mutated after creation (DDS S16: "current state = latest
    row, never a mutable boolean"). Granting writes a row with
    ``withdrawn_at=None``; withdrawing writes a **new** row where
    ``withdrawn_at`` is set to the same instant as its own ``granted_at`` —
    both columns fixed at INSERT time, never touched again. The latest row
    per ``(guest_profile, purpose)`` is the current state.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="guest_consents",
    )
    guest_profile = models.ForeignKey(
        GuestProfile,
        on_delete=models.RESTRICT,
        related_name="consents",
    )
    purpose = models.CharField(max_length=16, choices=ConsentPurpose.choices)
    basis = models.TextField()
    granted_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    objects = GuestConsentManager()

    class Meta:
        constraints = [
            status_constraint("purpose", ConsentPurpose, "guest_consent_valid_purpose"),
            models.UniqueConstraint(
                fields=["guest_profile", "purpose", "granted_at"],
                name="guest_consent_uq_profile_purpose_granted",
            ),
        ]
        indexes = [
            models.Index(fields=["guest_profile", "purpose", "withdrawn_at"]),
        ]

    def __str__(self) -> str:
        state = "withdrawn" if self.withdrawn_at else "granted"
        return f"{self.purpose} consent ({state}) for guest {self.guest_profile_id}"


class IdDocument(EntityMixin):
    """A passport/ID reference — only a hash is ever stored, never the raw number."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="id_documents",
    )
    guest_profile = models.ForeignKey(
        GuestProfile,
        on_delete=models.CASCADE,
        related_name="id_documents",
    )
    doc_type = models.CharField(max_length=32)
    ref_hash = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16,
        choices=DocumentStatus.choices,
        default=DocumentStatus.CURRENT,
    )

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            status_constraint("status", DocumentStatus, "id_document_valid_status"),
            models.UniqueConstraint(
                fields=["guest_profile", "doc_type", "ref_hash"],
                name="id_document_uq_profile_type_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["guest_profile"]),
        ]

    def __str__(self) -> str:
        return f"{self.doc_type} for guest {self.guest_profile_id} ({self.status})"
