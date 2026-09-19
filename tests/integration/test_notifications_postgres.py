"""Postgres integration tests — Notification concurrency proofs (M13).

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_housekeeping_postgres.py``. ``NotificationJob`` is
OPTIMISTICALLY locked (``VersionedMixin``) — no ``select_for_update()``
anywhere; the delivery race is resolved by ``ConcurrencyError``, exactly
like M12's ``HousekeepingTask``.
"""

import threading
from datetime import date, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.availability.services import AvailabilityService
from apps.notifications.models import (
    JobStatus,
    NotificationJob,
    NotificationTemplate,
    TemplateStatus,
)
from apps.notifications.projectors import NotificationProjector
from apps.notifications.providers import FakeEmailProvider
from apps.notifications.services import NotificationService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.properties.models import Property
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import RoomType
from apps.shared.exceptions import ConcurrencyError
from apps.shared.services.outbox import OutboxRelay
from apps.shared.value_objects import GuestCount, StayPeriod
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="real concurrent connections require Postgres"
)


def _bootstrap_reservation(*, guest_email: str, nights: int = 2):
    tenant = Tenant.objects.create(
        code=f"nt{timezone.now().timestamp()}", name="Notification Race", base_currency="NGN"
    )
    property_ = Property.objects.create(
        tenant=tenant,
        code="NT1",
        name="Notification Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
    )
    room_type = RoomType.objects.create(
        tenant=tenant,
        code="NT-KING",
        name="Notification King",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
    )
    rate_plan = PricingService.create_rate_plan(
        tenant=tenant,
        property=property_,
        room_type=room_type,
        code="NT-RACK",
        base_rate_minor_units=10000,
        currency=property_.currency,
    )
    PricingService.activate_rate_plan(rate_plan)
    draft = PolicyService.create_draft(tenant, "deposit", {"required": False}, date(2020, 1, 1))
    PolicyService.publish(draft.id)
    NotificationTemplate.objects.create(
        tenant=tenant,
        notification_type="reservation_created",
        channel="email",
        locale="en",
        subject="Your reservation {reservation_ref}",
        body="Hi {guest_name}!",
        status=TemplateStatus.PUBLISHED,
    )

    today = timezone.now().date()
    AvailabilityService.initialize_horizon(
        tenant_id=tenant.id,
        property_id=property_.id,
        room_type_id=room_type.id,
        total_units=10,
        start_date=today,
        horizon_days=nights,
    )
    stay = StayPeriod(today, today + timedelta(days=nights))
    line = ReservationLineRequest(
        room_type_id=room_type.id,
        stay_period=stay,
        guest_count=GuestCount(adults=1, children=0),
        quantity=1,
    )
    reservation = ReservationService.reserve(
        tenant=tenant,
        property=property_,
        lines=[line],
        idempotency_key="bootstrap-reserve",
        guest_email=guest_email,
    )
    OutboxRelay().publish_batch()
    return tenant, reservation


class TestDuplicateEventDelivery:
    """1. Duplicate event delivery — the projector processing the same
    already-relayed DomainEvent twice must never create a second job."""

    @pytest.mark.django_db(transaction=True)
    def test_reprocessing_creates_no_second_job(self):
        tenant, reservation = _bootstrap_reservation(guest_email="dup@example.com")
        NotificationProjector.process_batch()
        assert NotificationJob.objects.filter(tenant=tenant).count() == 1

        # Simulate a duplicate delivery attempt by resetting the checkpoint
        # and reprocessing the SAME already-consumed event.
        from apps.shared.models import ProjectionState

        ProjectionState.objects.filter(projection_name="notifications.dispatch").update(
            last_event_id=""
        )
        NotificationProjector.process_batch()
        assert NotificationJob.objects.filter(tenant=tenant).count() == 1


class TestConcurrentProjectorProcessing:
    """2. Two concurrent projector batches over the same new event."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_job_survives(self):
        tenant, reservation = _bootstrap_reservation(guest_email="proj@example.com")

        results = []
        barrier = threading.Barrier(2)

        def _run():
            try:
                barrier.wait(timeout=10)
                NotificationProjector.process_batch()
                results.append(None)
            except Exception as exc:  # noqa: BLE001
                results.append(exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_run)
        thread_b = threading.Thread(target=_run)
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert len(results) == 2
        assert NotificationJob.objects.filter(tenant=tenant).count() == 1


class TestConcurrentDelivery:
    """3. Concurrent delivery of the SAME job — real PostgreSQL connections."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_logical_successful_delivery(self):
        tenant, reservation = _bootstrap_reservation(guest_email="deliver@example.com")
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get(tenant=tenant)

        results: dict[str, tuple[str | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str) -> None:
            try:
                barrier.wait(timeout=10)
                outcome = NotificationService.deliver(job_id=job.id, provider=FakeEmailProvider())
                results[caller] = (outcome.status, None)
            except Exception as exc:  # noqa: BLE001
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_attempt, args=("A",))
        thread_b = threading.Thread(target=_attempt, args=("B",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (status, exc) in results.items() if exc is None]
        failures = [(c, exc) for c, (status, exc) in results.items() if exc is not None]
        assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
        assert len(failures) == 1, f"expected exactly one loser, got {results!r}"

        loser, loser_exc = failures[0]
        assert isinstance(loser_exc, ConcurrencyError), (
            f"loser must fail with ConcurrencyError, got {loser_exc!r}"
        )

        job.refresh_from_db()
        assert job.status == JobStatus.DELIVERED
        assert job.delivery_attempts.count() == 1


class TestProviderFailureThenRetry:
    """4. Provider failure then retry succeeds."""

    @pytest.mark.django_db(transaction=True)
    def test_failure_then_successful_retry(self):
        tenant, reservation = _bootstrap_reservation(guest_email="retry@example.com")
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get(tenant=tenant)

        provider = FakeEmailProvider()
        key = NotificationService._idempotency_key(job.id)
        provider.fail_next(key)

        failed = NotificationService.deliver(job_id=job.id, provider=provider)
        assert failed.status == JobStatus.FAILED
        assert failed.retry_count == 1

        delivered = NotificationService.deliver(job_id=job.id, provider=provider)
        assert delivered.status == JobStatus.DELIVERED
        assert delivered.delivery_attempts.count() == 2


class TestFullPipelineReplayedTwice:
    """5 & 6. The complete event -> job -> delivery pipeline, replayed
    twice, never creates a second logical Job."""

    @pytest.mark.django_db(transaction=True)
    def test_replaying_the_pipeline_is_idempotent(self):
        tenant, reservation = _bootstrap_reservation(guest_email="pipeline@example.com")

        NotificationProjector.process_batch()
        job_first = NotificationJob.objects.get(tenant=tenant)
        NotificationService.deliver(job_id=job_first.id, provider=FakeEmailProvider())

        # Replay: re-run the projector (no new events) and attempt delivery
        # again on whatever "pending" work exists (there should be none).
        NotificationProjector.process_batch()
        assert NotificationJob.objects.filter(tenant=tenant).count() == 1

        job_first.refresh_from_db()
        assert job_first.status == JobStatus.DELIVERED
        assert job_first.delivery_attempts.count() == 1
