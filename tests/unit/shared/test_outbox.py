"""Unit tests for the transactional outbox — producer and relay (M1.3, DR-08).

Order follows the M1.3 adaptation:
producer → relay promotion → idempotent promotion → dead-lettering → the full
round trip (state change → outbox → relay → domain_event → idempotent consumer).
The real shared tables exist via migrations, so tests use the ORM directly.
"""

from unittest import mock

import pytest
from django.db import connection
from django.utils import timezone
from django_fsm import FSMField

from apps.shared.models import (
    DomainEvent,
    EntityMixin,
    OutboxEvent,
    OutboxEventStatus,
    ProjectionState,
)
from apps.shared.services.outbox import OutboxRelay, OutboxService
from apps.shared.workflows.runner import WorkflowRunner, workflow_transition

TENANT = 7


class BookingRoundTripProbe(EntityMixin):
    """A probe workflow: EntityMixin + one django-fsm transition with an event."""
    state = FSMField(default="pending", protected=True)

    class Meta:
        app_label = "probes"

    @workflow_transition(source="pending", target="confirmed", event="booking.confirmed")
    def confirm(self):
        pass


def _ensure_table(model):
    if model._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(model)


@pytest.fixture(scope="module")
def booking_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(BookingRoundTripProbe)
    yield BookingRoundTripProbe


def _purge(model):
    """Test teardown of append-only tables must bypass the ORM guard.

    The manager refuses delete() on purpose; the schema-level trigger/RLS guard
    arrives in M2. For tests, purge via raw SQL — the same bypass a future
    maintenance job would need to archive rows.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {model._meta.db_table}")


@pytest.fixture(autouse=True)
def _clean():
    yield
    _purge(OutboxEvent)
    _purge(DomainEvent)
    _purge(ProjectionState)


class TestProducer:
    @pytest.mark.django_db
    def test_record_event_creates_a_pending_row(self):
        row = OutboxService.record_event(
            event_type="booking.confirmed",
            tenant_id=TENANT,
            aggregate_type="booking",
            aggregate_id="42",
            payload={"from": "pending", "to": "confirmed"},
        )

        assert row.status == OutboxEventStatus.PENDING
        assert row.attempts == 0
        assert row.payload == {"from": "pending", "to": "confirmed"}
        assert OutboxEvent.objects.count() == 1

    @pytest.mark.django_db
    def test_record_event_defaults_payload_and_aggregate(self):
        row = OutboxService.record_event(event_type="booking.cancelled", tenant_id=TENANT)

        assert row.payload == {}
        assert row.aggregate_type == ""
        assert row.aggregate_id == ""
        assert row.event_version == 1


class TestRelayPromotion:
    @pytest.mark.django_db
    def test_relay_promotes_pending_row_to_domain_event(self):
        OutboxService.record_event(
            event_type="booking.confirmed",
            tenant_id=TENANT,
            aggregate_type="booking",
            aggregate_id="42",
            payload={"from": "pending", "to": "confirmed"},
        )

        published = OutboxRelay().publish_batch()

        assert published == 1
        event = DomainEvent.objects.get()
        assert event.event_type == "booking.confirmed"
        assert event.aggregate_type == "booking"
        assert event.aggregate_id == "42"
        assert event.payload == {"from": "pending", "to": "confirmed"}
        # The outbox row is marked published, not deleted.
        row = OutboxEvent.objects.get()
        assert row.status == OutboxEventStatus.PUBLISHED

    @pytest.mark.django_db
    def test_relay_promotes_oldest_first(self):
        first = OutboxService.record_event(event_type="a", tenant_id=TENANT)
        second = OutboxService.record_event(event_type="b", tenant_id=TENANT)
        # second gets the *older* created_at by hand.
        OutboxEvent.objects.filter(pk=first.pk).update(created_at=timezone.now())
        OutboxEvent.objects.filter(pk=second.pk).update(
            created_at=timezone.now() - timezone.timedelta(minutes=5)
        )

        OutboxRelay().publish_batch()

        events = list(DomainEvent.objects.order_by("occurred_at"))
        assert [e.event_type for e in events] == ["b", "a"]

    @pytest.mark.django_db
    def test_double_relay_does_not_duplicate_domain_events(self):
        OutboxService.record_event(
            event_type="booking.confirmed", tenant_id=TENANT, aggregate_id="42"
        )

        OutboxRelay().publish_batch()
        second_run = OutboxRelay().publish_batch()

        # The second scan finds nothing pending (already published) — and even
        # a forced re-run converges on ONE DomainEvent via the (tenant, uuid) UQ.
        assert second_run == 0
        assert DomainEvent.objects.count() == 1
        assert OutboxEvent.objects.get().status == OutboxEventStatus.PUBLISHED


class TestDeadLettering:
    @pytest.mark.django_db
    def test_failed_promotion_increments_attempts_and_dead_letters(self):
        OutboxService.record_event(event_type="poisoned", tenant_id=TENANT)
        relay = OutboxRelay(max_attempts=1)

        with mock.patch(
            "apps.shared.services.outbox.DomainEvent.objects.get_or_create",
            side_effect=RuntimeError("cannot insert"),
        ):
            published = relay.publish_batch()

        assert published == 0
        row = OutboxEvent.objects.get()
        assert row.status == OutboxEventStatus.DEAD_LETTERED
        assert row.attempts == 1
        assert "cannot insert" in row.last_error
        assert DomainEvent.objects.count() == 0

    @pytest.mark.django_db
    def test_below_max_attempts_stays_pending_then_recovers(self):
        OutboxService.record_event(event_type="flaky", tenant_id=TENANT)
        relay = OutboxRelay(max_attempts=3)

        with mock.patch(
            "apps.shared.services.outbox.DomainEvent.objects.get_or_create",
            side_effect=RuntimeError("first attempt fails"),
        ):
            relay.publish_batch()

        row = OutboxEvent.objects.get()
        assert row.status == OutboxEventStatus.PENDING  # one retry left
        assert row.attempts == 1

        # Next run succeeds (the failure is gone) — the row recovers.
        published = relay.publish_batch()
        assert published == 1
        row.refresh_from_db()
        assert row.status == OutboxEventStatus.PUBLISHED


class TestRoundTrip:
    @pytest.mark.django_db
    def test_state_change_to_idempotent_consumer(self, booking_probe):
        """The M1.3 review-gate round trip:
        state change → outbox (same txn) → relay → domain_event → idempotent consumer."""
        # 1-2. State change writes an outbox row in the same transaction.
        booking = booking_probe.objects.create(tenant_id=TENANT)
        WorkflowRunner(booking).run("confirm", reason="guest confirmed")
        assert OutboxEvent.objects.filter(event_type="booking.confirmed").count() == 1

        # 3. Relay promotes the outbox row into the durable event log.
        assert OutboxRelay().publish_batch() == 1
        event = DomainEvent.objects.get(event_type="booking.confirmed")
        assert event.aggregate_type == "bookingroundtripprobe"
        assert event.payload == {"from": "pending", "to": "confirmed"}

        # 4. An idempotent consumer folds the event into a projection exactly once.
        assert _consume(event) is True
        assert _consume(event) is False  # already processed — no double fold
        state = ProjectionState.objects.get(projection_name="test_projection")
        assert state.last_event_id == str(event.pk)


def _consume(event: DomainEvent) -> bool:
    """A minimal idempotent projection consumer using the checkpoint."""
    state, _ = ProjectionState.objects.get_or_create(
        projection_name="test_projection",
        defaults={"last_event_id": "", "last_processed_at": None},
    )
    if state.last_event_id == str(event.pk):
        return False  # already folded — idempotent
    state.last_event_id = str(event.pk)
    state.last_processed_at = timezone.now()
    state.save()
    return True
