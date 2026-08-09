"""Unit tests for the audit log and AppendOnlyMixin immutability (M1.5, E8).

Order: same-transaction recording → typed refs (no GFK) → actor FK behavior →
append-only immutability (the review-gate audit immutability test) → edge cases.
"""

import pytest
from django.db import connection, transaction

from apps.shared.exceptions import AppendOnlyViolation
from apps.shared.models import AuditLog
from apps.shared.services.audit import AuditService

TENANT = 7


@pytest.fixture(autouse=True)
def _clean():
    yield
    # Test teardown of an append-only table must bypass the ORM guard (the
    # schema-level trigger arrives in M2) — purge via raw SQL.
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {AuditLog._meta.db_table}")


class TestRecording:
    @pytest.mark.django_db
    def test_record_writes_a_row_with_typed_refs_and_before_after(self):
        entry = AuditService.record(
            tenant_id=TENANT,
            entity_type="booking",
            entity_id="42",
            action="update",
            before={"status": "pending"},
            after={"status": "confirmed"},
            reason="guest confirmed",
            request_id="req-1",
        )

        assert entry.entity_type == "booking"
        assert entry.entity_id == "42"
        assert entry.action == "update"
        assert entry.before == {"status": "pending"}
        assert entry.after == {"status": "confirmed"}
        assert entry.reason == "guest confirmed"
        assert entry.request_id == "req-1"

    @pytest.mark.django_db
    def test_actor_is_a_real_fk_with_set_null(self):
        from django.contrib.auth import get_user_model

        actor = get_user_model().objects.create_user(email="desk-agent@example.com")
        entry = AuditService.record(
            tenant_id=TENANT, entity_type="booking", entity_id="42",
            action="confirm", actor=actor,
        )
        entry.refresh_from_db()
        assert entry.actor_id == actor.pk

        actor.delete()  # history survives the actor's deletion
        entry.refresh_from_db()
        assert entry.actor_id is None

    @pytest.mark.django_db
    def test_refs_are_typed_strings_not_a_generic_foreign_key(self):
        # E8: no GFK — entity_type/entity_id are plain strings, so the audit
        # table holds no polymorphic FK and queries target them directly.
        field_names = {f.name for f in AuditLog._meta.get_fields()}
        assert "content_type" not in field_names
        assert "object_id" not in field_names

    @pytest.mark.django_db
    def test_actor_can_be_null_for_system_actions(self):
        entry = AuditService.record(
            tenant_id=TENANT, entity_type="policy", entity_id="9", action="publish"
        )
        assert entry.actor_id is None


class TestSameTransaction:
    @pytest.mark.django_db(transaction=True)
    def test_audit_rolls_back_with_the_change_it_records(self):
        # The same-transaction contract: the audit entry and the change commit
        # or roll back together — the log never records something that didn't
        # happen, nor misses something that did.
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                AuditService.record(
                    tenant_id=TENANT, entity_type="booking", entity_id="42",
                    action="confirm", after={"status": "confirmed"},
                )
                raise RuntimeError("the change itself failed")

        assert AuditLog.objects.count() == 0

    @pytest.mark.django_db(transaction=True)
    def test_audit_commits_with_the_change(self):
        with transaction.atomic():
            AuditService.record(
                tenant_id=TENANT, entity_type="booking", entity_id="42",
                action="confirm", after={"status": "confirmed"},
            )

        assert AuditLog.objects.count() == 1


class TestImmutability:
    @pytest.mark.django_db
    def test_update_via_save_raises(self):
        entry = AuditService.record(
            tenant_id=TENANT, entity_type="booking", entity_id="42", action="create"
        )

        entry.reason = "forged"
        with pytest.raises(AppendOnlyViolation):
            entry.save()

    @pytest.mark.django_db
    def test_delete_raises(self):
        entry = AuditService.record(
            tenant_id=TENANT, entity_type="booking", entity_id="42", action="create"
        )

        with pytest.raises(AppendOnlyViolation):
            entry.delete()
        assert AuditLog.objects.count() == 1

    @pytest.mark.django_db
    def test_queryset_update_and_delete_raise(self):
        AuditService.record(
            tenant_id=TENANT, entity_type="booking", entity_id="42", action="create"
        )

        with pytest.raises(AppendOnlyViolation):
            AuditLog.objects.update(reason="bulk forged")
        with pytest.raises(AppendOnlyViolation):
            AuditLog.objects.delete()
        assert AuditLog.objects.count() == 1

    @pytest.mark.django_db
    def test_domain_event_log_is_append_only_too(self):
        from apps.shared.models import DomainEvent
        from apps.shared.services.outbox import OutboxRelay, OutboxService

        OutboxService.record_event(event_type="booking.confirmed", tenant_id=TENANT)
        OutboxRelay().publish_batch()  # promote the outbox row into the log
        event = DomainEvent.objects.get()

        with pytest.raises(AppendOnlyViolation):
            event.save()
        with pytest.raises(AppendOnlyViolation):
            DomainEvent.objects.delete()
