"""Guest lifecycle tests (M5)."""
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.guests.models import (
    ConsentPurpose,
    DocumentStatus,
    GuestConsent,
    GuestProfile,
    GuestStatus,
    IdDocument,
    PreferenceCategory,
)
from apps.guests.services import (
    GuestQuery,
    GuestResolutionError,
    GuestService,
    InvalidMergeTarget,
    ProfileMergeService,
)
from apps.shared.exceptions import AppendOnlyViolation
from apps.shared.value_objects import GuestName


@pytest.mark.django_db
class TestGuestResolution:
    def test_resolve_creates_new_profile_when_none_exists(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        assert profile.status == GuestStatus.ACTIVE
        assert profile.primary_email == "ada@example.com"

    def test_resolve_finds_existing_profile_by_email(self, tenant):
        first = GuestService.resolve(tenant, email="ada@example.com")
        second = GuestService.resolve(tenant, email="ada@example.com")

        assert second.id == first.id
        assert GuestProfile.objects.filter(tenant=tenant).count() == 1

    def test_resolve_finds_existing_profile_by_phone(self, tenant):
        first = GuestService.resolve(tenant, phone="+2348012345678")
        second = GuestService.resolve(tenant, phone="+2348012345678")

        assert second.id == first.id

    def test_resolve_email_is_case_insensitive(self, tenant):
        first = GuestService.resolve(tenant, email="Ada@Example.com")
        second = GuestService.resolve(tenant, email="ada@example.com")

        assert second.id == first.id

    def test_resolve_requires_email_or_phone(self, tenant):
        with pytest.raises(GuestResolutionError):
            GuestService.resolve(tenant)

    def test_resolve_scoped_to_tenant(self, tenant, tenant2):
        first = GuestService.resolve(tenant, email="ada@example.com")
        second = GuestService.resolve(tenant2, email="ada@example.com")

        assert first.id != second.id
        assert first.tenant_id == tenant.id
        assert second.tenant_id == tenant2.id

    def test_resolve_stores_name_and_language(self, tenant):
        name = GuestName(given_name="Ada", family_name="Lovelace")
        profile = GuestService.resolve(tenant, email="ada@example.com", name=name, language="en")

        assert profile.name == {
            "given_name": "Ada",
            "family_name": "Lovelace",
            "display_name": "Ada Lovelace",
        }
        assert profile.language == "en"

    def test_resolve_race_two_concurrent_creates_yield_one_profile(self, tenant):
        """Simulates the concurrent find-or-create race (DDS S16 review gate):
        the pre-create lookup misses, another writer's row lands first, our
        INSERT hits the unique constraint, and we recover by re-reading."""
        winner = GuestProfile.objects.create(
            tenant=tenant, primary_email="race@example.com", status=GuestStatus.ACTIVE
        )
        with patch.object(GuestQuery, "find_by_identity") as mock_find:
            mock_find.side_effect = [None, winner]
            result = GuestService.resolve(tenant, email="race@example.com")

        assert result.id == winner.id
        assert (
            GuestProfile.objects.filter(tenant=tenant, primary_email="race@example.com").count()
            == 1
        )


@pytest.mark.django_db
class TestGuestPreferences:
    def test_set_preference_creates_row(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        pref = GuestService.update_preference(profile, PreferenceCategory.ROOM, {"floor": "high"})

        assert pref.category == PreferenceCategory.ROOM
        assert pref.value == {"floor": "high"}

    def test_set_preference_upserts_existing_category(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        GuestService.update_preference(profile, PreferenceCategory.ROOM, {"floor": "high"})

        updated = GuestService.update_preference(profile, PreferenceCategory.ROOM, {"floor": "low"})

        assert updated.value == {"floor": "low"}
        assert GuestQuery.preferences(profile).count() == 1

    def test_invalid_category_rejected(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        with pytest.raises(ValueError):
            GuestService.update_preference(profile, "not-a-category", {})


@pytest.mark.django_db
class TestGuestConsent:
    def test_record_consent_creates_new_row(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        consent = GuestService.record_consent(profile, ConsentPurpose.MARKETING, "consent")

        assert consent.withdrawn_at is None
        assert consent.basis == "consent"

    def test_current_state_is_latest_row(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        GuestService.record_consent(profile, ConsentPurpose.MARKETING, "consent")

        GuestService.withdraw_consent(profile, ConsentPurpose.MARKETING, "guest requested")

        current = GuestQuery.current_consent(profile, ConsentPurpose.MARKETING)
        assert current.withdrawn_at is not None
        assert GuestQuery.has_active_consent(profile, ConsentPurpose.MARKETING) is False

    def test_withdraw_consent_does_not_mutate_existing_row(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        granted = GuestService.record_consent(profile, ConsentPurpose.MARKETING, "consent")

        GuestService.withdraw_consent(profile, ConsentPurpose.MARKETING, "guest requested")

        granted.refresh_from_db()
        assert granted.withdrawn_at is None
        assert GuestConsent.objects.filter(guest_profile=profile).count() == 2

    def test_consent_history_is_append_only(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        consent = GuestService.record_consent(profile, ConsentPurpose.MARKETING, "consent")

        with pytest.raises(AppendOnlyViolation):
            consent.basis = "changed"
            consent.save()

    def test_consent_rows_cannot_be_deleted(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        consent = GuestService.record_consent(profile, ConsentPurpose.MARKETING, "consent")

        with pytest.raises(AppendOnlyViolation):
            consent.delete()

    def test_invalid_consent_purpose_rejected(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        with pytest.raises(ValidationError):
            consent = GuestConsent(
                tenant=tenant,
                guest_profile=profile,
                purpose="not-a-purpose",
                basis="consent",
                granted_at=profile.created_at,
            )
            consent.full_clean()


@pytest.mark.django_db
class TestIdDocument:
    def test_add_id_document_stores_hash_only(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        document = GuestService.add_id_document(profile, "passport", "A1234567")

        assert document.ref_hash != "A1234567"
        assert len(document.ref_hash) == 64  # sha256 hexdigest
        assert document.status == DocumentStatus.CURRENT

    def test_duplicate_doc_type_and_hash_rejected(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        document = GuestService.add_id_document(profile, "passport", "A1234567")

        with pytest.raises(IntegrityError):
            IdDocument.objects.create(
                tenant=tenant,
                guest_profile=profile,
                doc_type="passport",
                ref_hash=document.ref_hash,
            )

    def test_remove_id_document_sets_status_removed(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        document = GuestService.add_id_document(profile, "passport", "A1234567")

        removed = GuestService.remove_id_document(document)

        assert removed.status == DocumentStatus.REMOVED


@pytest.mark.django_db
class TestProfileMerge:
    def test_merge_sets_merged_into_and_status(self, tenant):
        winner = GuestService.resolve(tenant, email="ada@example.com")
        loser = GuestService.resolve(tenant, phone="+2348012345678")

        result = ProfileMergeService.merge(loser, winner)

        loser.refresh_from_db()
        assert result.id == winner.id
        assert loser.merged_into_id == winner.id
        assert loser.status == GuestStatus.MERGED

    def test_merge_into_self_raises(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        with pytest.raises(InvalidMergeTarget):
            ProfileMergeService.merge(profile, profile)

    def test_merge_already_merged_profile_raises(self, tenant):
        winner = GuestService.resolve(tenant, email="ada@example.com")
        loser = GuestService.resolve(tenant, phone="+2348012345678")
        other = GuestService.resolve(tenant, phone="+2348099999999")
        ProfileMergeService.merge(loser, winner)

        with pytest.raises(InvalidMergeTarget):
            ProfileMergeService.merge(loser, other)

    def test_merge_is_never_automatic(self, tenant):
        """resolve() never sets merged_into — only ProfileMergeService.merge() does."""
        profile = GuestService.resolve(tenant, email="ada@example.com")
        GuestService.resolve(tenant, email="ada@example.com")

        assert profile.merged_into_id is None

    def test_merged_profile_email_can_be_reused(self, tenant):
        winner = GuestService.resolve(tenant, email="winner@example.com")
        loser = GuestService.resolve(tenant, email="loser@example.com")
        ProfileMergeService.merge(loser, winner)

        # loser's old email is free again since merged profiles are excluded
        # from the active-uniqueness partial index.
        reused = GuestService.resolve(tenant, email="loser@example.com")
        assert reused.id != loser.id
        assert reused.primary_email == "loser@example.com"


@pytest.mark.django_db
class TestErasure:
    def test_erase_sets_erased_at_and_status_closed(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        erased = GuestService.erase(profile)

        assert erased.status == GuestStatus.CLOSED
        assert erased.erased_at is not None
        assert erased.erasure_ref

    def test_erase_scrubs_pii_fields(self, tenant):
        name = GuestName(given_name="Ada", family_name="Lovelace")
        profile = GuestService.resolve(tenant, email="ada@example.com", name=name)

        erased = GuestService.erase(profile)

        assert erased.primary_email is None
        assert erased.name == {}

    def test_erase_never_hard_deletes_profile_row(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")

        GuestService.erase(profile)

        assert GuestProfile.objects.filter(id=profile.id).exists()

    def test_erase_leaves_fk_referencing_rows_intact(self, tenant):
        profile = GuestService.resolve(tenant, email="ada@example.com")
        GuestService.record_consent(profile, ConsentPurpose.MARKETING, "consent")
        GuestService.update_preference(profile, PreferenceCategory.ROOM, {"floor": "high"})
        document = GuestService.add_id_document(profile, "passport", "A1234567")

        GuestService.erase(profile)

        assert GuestConsent.objects.filter(guest_profile=profile).count() == 1
        assert GuestQuery.preferences(profile).count() == 1
        assert IdDocument.objects.filter(id=document.id).exists()


@pytest.mark.django_db
class TestTenantIsolation:
    def test_tenant_isolation(self, tenant, tenant2):
        GuestService.resolve(tenant, email="ada@example.com")
        GuestService.resolve(tenant2, email="grace@example.com")

        assert GuestProfile.objects.filter(tenant=tenant).count() == 1
        assert GuestProfile.objects.filter(tenant=tenant2).count() == 1
