"""Guest lifecycle services — identity resolution, consent, merge, erasure (M5).

Authoritative references:
- SDD S11.9 — Guest identity (the lifecycle hub)
- DDS S16 — Guest Profile
- Implementation roadmap M5
"""

import hashlib
import uuid
from datetime import timedelta

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.guests.models import (
    DocumentStatus,
    GuestConsent,
    GuestPreference,
    GuestProfile,
    GuestStatus,
    IdDocument,
    PreferenceCategory,
)
from apps.shared.services.outbox import OutboxService
from apps.shared.value_objects import Email, GuestName, PhoneNumber


class GuestResolutionError(Exception):
    """Raised when resolve() is called without any identifying field."""


class InvalidMergeTarget(Exception):
    """Raised when a merge is attempted with an invalid source/target pair."""


class GuestQuery:
    """Read-model selector — the mirror of GuestService (identity resolution,
    consent reads for Notifications' future eligibility checks)."""

    @staticmethod
    def find_by_identity(
        tenant, *, email: str | None = None, phone: str | None = None
    ) -> GuestProfile | None:
        """Find an active, non-merged profile by an already-normalized email/phone.

        Internal to resolution (email/phone must already be canonical). See
        ``find_by_email``/``find_by_phone`` for raw external input.
        """
        if not email and not phone:
            return None
        qs = GuestProfile.objects.filter(
            tenant=tenant, erased_at__isnull=True, merged_into__isnull=True
        )
        if email and phone:
            qs = qs.filter(models.Q(primary_email=email) | models.Q(primary_phone=phone))
        elif email:
            qs = qs.filter(primary_email=email)
        else:
            qs = qs.filter(primary_phone=phone)
        return qs.first()

    @staticmethod
    def find_by_email(tenant, email: str) -> GuestProfile | None:
        return GuestQuery.find_by_identity(tenant, email=str(Email(email)))

    @staticmethod
    def find_by_phone(tenant, phone: str) -> GuestProfile | None:
        return GuestQuery.find_by_identity(tenant, phone=str(PhoneNumber(phone)))

    @staticmethod
    def for_tenant(tenant):
        return GuestProfile.objects.filter(tenant=tenant)

    @staticmethod
    def preferences(guest_profile: GuestProfile):
        return GuestPreference.objects.filter(guest_profile=guest_profile)

    @staticmethod
    def current_consent(guest_profile: GuestProfile, purpose: str) -> GuestConsent | None:
        """The latest consent row for a purpose — current state = latest row."""
        return (
            GuestConsent.objects.filter(guest_profile=guest_profile, purpose=purpose)
            .order_by("-granted_at")
            .first()
        )

    @staticmethod
    def has_active_consent(guest_profile: GuestProfile, purpose: str) -> bool:
        current = GuestQuery.current_consent(guest_profile, purpose)
        return current is not None and current.withdrawn_at is None


class GuestService:
    """Identity resolution, preferences, consent lifecycle, erasure (DDS S16)."""

    @staticmethod
    def _next_granted_at(guest_profile: GuestProfile, purpose: str):
        """A timestamp strictly after the current latest row's ``granted_at``.

        ``granted_at`` is part of the append-only uniqueness key (DDS S16:
        ``UQ (guest_profile_id, purpose, granted_at)``); two consent events
        for the same purpose in quick succession can otherwise land in the
        same clock tick (observed on Windows' coarser timer resolution) and
        collide. Never rewinds — only nudges forward when needed.
        """
        now = timezone.now()
        current = GuestQuery.current_consent(guest_profile, purpose)
        if current is not None and now <= current.granted_at:
            return current.granted_at + timedelta(microseconds=1)
        return now

    @staticmethod
    def resolve(
        tenant,
        *,
        email: str | None = None,
        phone: str | None = None,
        name: GuestName | None = None,
        language: str = "",
    ) -> GuestProfile:
        """Find-or-create by email/phone within the tenant — the booking-time
        hot path. Two concurrent resolves for the same identity converge on
        one profile: the loser's INSERT hits the partial unique constraint
        and recovers by re-reading the winner's row (never a second profile).
        """
        if not email and not phone:
            raise GuestResolutionError(
                "resolve() requires at least one of email or phone to identify a guest."
            )
        normalized_email = str(Email(email)) if email else None
        normalized_phone = str(PhoneNumber(phone)) if phone else None

        existing = GuestQuery.find_by_identity(
            tenant, email=normalized_email, phone=normalized_phone
        )
        if existing is not None:
            return existing

        try:
            with transaction.atomic():
                profile = GuestProfile.objects.create(
                    tenant=tenant,
                    primary_email=normalized_email,
                    primary_phone=normalized_phone,
                    name=name.to_dict() if name else {},
                    language=language,
                    status=GuestStatus.ACTIVE,
                )
                OutboxService.record_event(
                    event_type="guest.identified",
                    tenant_id=tenant.id,
                    payload={"guest_id": profile.id},
                    aggregate_type="guestprofile",
                    aggregate_id=str(profile.id),
                )
                return profile
        except IntegrityError:
            existing = GuestQuery.find_by_identity(
                tenant, email=normalized_email, phone=normalized_phone
            )
            if existing is None:
                raise
            return existing

    @staticmethod
    def update_preference(
        guest_profile: GuestProfile, category: str, value: dict
    ) -> GuestPreference:
        if category not in PreferenceCategory.values:
            raise ValueError(f"Unknown preference category: {category!r}")
        preference, _ = GuestPreference.objects.update_or_create(
            guest_profile=guest_profile,
            category=category,
            defaults={"tenant": guest_profile.tenant, "value": value},
        )
        return preference

    @staticmethod
    def record_consent(guest_profile: GuestProfile, purpose: str, basis: str) -> GuestConsent:
        """Append a new grant row. Never mutates prior history."""
        with transaction.atomic():
            consent = GuestConsent.objects.create(
                tenant=guest_profile.tenant,
                guest_profile=guest_profile,
                purpose=purpose,
                basis=basis,
                granted_at=GuestService._next_granted_at(guest_profile, purpose),
                withdrawn_at=None,
            )
            OutboxService.record_event(
                event_type="consent.updated",
                tenant_id=guest_profile.tenant_id,
                payload={"guest_id": guest_profile.id, "purpose": purpose, "state": "granted"},
                aggregate_type="guestconsent",
                aggregate_id=str(consent.id),
            )
            return consent

    @staticmethod
    def withdraw_consent(guest_profile: GuestProfile, purpose: str, basis: str) -> GuestConsent:
        """Append a new withdrawal row (``granted_at == withdrawn_at``). Never
        mutates the row(s) that granted consent."""
        with transaction.atomic():
            now = GuestService._next_granted_at(guest_profile, purpose)
            consent = GuestConsent.objects.create(
                tenant=guest_profile.tenant,
                guest_profile=guest_profile,
                purpose=purpose,
                basis=basis,
                granted_at=now,
                withdrawn_at=now,
            )
            OutboxService.record_event(
                event_type="consent.updated",
                tenant_id=guest_profile.tenant_id,
                payload={"guest_id": guest_profile.id, "purpose": purpose, "state": "withdrawn"},
                aggregate_type="guestconsent",
                aggregate_id=str(consent.id),
            )
            return consent

    @staticmethod
    def add_id_document(
        guest_profile: GuestProfile, doc_type: str, raw_document_number: str
    ) -> IdDocument:
        """Hashes the raw number immediately; the raw value is never persisted."""
        ref_hash = hashlib.sha256(raw_document_number.encode("utf-8")).hexdigest()
        return IdDocument.objects.create(
            tenant=guest_profile.tenant,
            guest_profile=guest_profile,
            doc_type=doc_type,
            ref_hash=ref_hash,
            status=DocumentStatus.CURRENT,
        )

    @staticmethod
    def remove_id_document(id_document: IdDocument) -> IdDocument:
        id_document.status = DocumentStatus.REMOVED
        id_document.save()
        return id_document

    @staticmethod
    def erase(guest_profile: GuestProfile, reason: str = "") -> GuestProfile:
        """GDPR erasure: anonymize + erased_at. Never DELETE. Consent rows are
        kept as proof; preferences and id documents remain (still FK-linked)."""
        with transaction.atomic():
            guest_profile.name = {}
            guest_profile.primary_email = None
            guest_profile.primary_phone = None
            guest_profile.language = ""
            guest_profile.status = GuestStatus.CLOSED
            guest_profile.erased_at = timezone.now()
            guest_profile.erasure_ref = uuid.uuid4().hex
            guest_profile.save()
            OutboxService.record_event(
                event_type="guest.erased",
                tenant_id=guest_profile.tenant_id,
                payload={
                    "guest_id": guest_profile.id,
                    "erasure_ref": guest_profile.erasure_ref,
                    "reason": reason,
                },
                aggregate_type="guestprofile",
                aggregate_id=str(guest_profile.id),
            )
            return guest_profile


class ProfileMergeService:
    """Human-reviewed profile merge — never automatic (DDS S16 invariant #2)."""

    @staticmethod
    def merge(from_profile: GuestProfile, into_profile: GuestProfile) -> GuestProfile:
        if from_profile.id == into_profile.id:
            raise InvalidMergeTarget("Cannot merge a guest profile into itself.")
        if from_profile.status != GuestStatus.ACTIVE:
            raise InvalidMergeTarget(
                f"Cannot merge profile in status {from_profile.status!r}; "
                "only active profiles can be merged."
            )
        if into_profile.status != GuestStatus.ACTIVE:
            raise InvalidMergeTarget(
                f"Cannot merge into profile in status {into_profile.status!r}; "
                "the merge target must be active."
            )
        with transaction.atomic():
            from_profile.merged_into = into_profile
            from_profile.status = GuestStatus.MERGED
            from_profile.save()
            OutboxService.record_event(
                event_type="guest.merged",
                tenant_id=from_profile.tenant_id,
                payload={"from_guest_id": from_profile.id, "into_guest_id": into_profile.id},
                aggregate_type="guestprofile",
                aggregate_id=str(from_profile.id),
            )
            return into_profile
