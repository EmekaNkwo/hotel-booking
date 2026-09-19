"""Postgres integration tests — Housekeeping concurrency proofs (M12).

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_allocation_postgres.py``.

Two real, independent connections/transactions per race (Django opens one
connection per OS thread lazily — no mocking of concurrency), the same
shape as the M7-M11 race proofs. ``HousekeepingTask`` is OPTIMISTICALLY
locked (``VersionedMixin``, M12 ruling) — no ``select_for_update()`` is used
on it anywhere in these tests either; the race is resolved by
``ConcurrencyError``, not a blocked lock.
"""

import threading
from datetime import date, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.allocation.exceptions import NoEligibleRoom
from apps.allocation.models import AllocationRecord
from apps.allocation.services import AllocationService
from apps.availability.services import AvailabilityService
from apps.bookings.services import BookingService
from apps.housekeeping.models import HousekeepingTask, Inspection, TaskStatus
from apps.housekeeping.services import HousekeepingService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.properties.models import Property
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import Room, RoomType
from apps.shared.exceptions import ConcurrencyError
from apps.shared.value_objects import GuestCount, StayPeriod
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="real concurrent connections require Postgres"
)


def _bootstrap(*, room_count: int = 1, nights: int = 2):
    tenant = Tenant.objects.create(
        code=f"hk{timezone.now().timestamp()}", name="Housekeeping Race", base_currency="NGN"
    )
    property_ = Property.objects.create(
        tenant=tenant,
        code="HK1",
        name="Housekeeping Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
    )
    room_type = RoomType.objects.create(
        tenant=tenant,
        code="HK-KING",
        name="Housekeeping King",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
    )
    rooms = [
        Room.objects.create(
            tenant=tenant,
            property=property_,
            room_type=room_type,
            code=f"R{i}",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        for i in range(room_count)
    ]
    rate_plan = PricingService.create_rate_plan(
        tenant=tenant,
        property=property_,
        room_type=room_type,
        code="HK-RACK",
        base_rate_minor_units=10000,
        currency=property_.currency,
    )
    PricingService.activate_rate_plan(rate_plan)
    draft = PolicyService.create_draft(tenant, "deposit", {"required": False}, date(2020, 1, 1))
    PolicyService.publish(draft.id)

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
    return tenant, property_, room_type, rooms, stay


def _checked_in_line(tenant, property_, room_type, stay, *, guest_email, key_prefix):
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
        idempotency_key=f"{key_prefix}-reserve",
        guest_email=guest_email,
    )
    ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
    booking = BookingService.confirm(
        tenant_id=tenant.id,
        reservation_id=reservation.id,
        idempotency_key=f"{key_prefix}-confirm",
    )
    booking_line = booking.lines.get()
    AllocationService.allocate_line(
        tenant_id=tenant.id,
        booking_line_id=booking_line.id,
        idempotency_key=f"{key_prefix}-allocate",
    )
    booking_line.refresh_from_db()
    return booking_line


class TestConcurrentCompleteCleaningRace:
    """Test 1: two workers complete the same task concurrently."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_completion_wins(self):
        tenant, property_, room_type, rooms, stay = _bootstrap(room_count=1)
        line = _checked_in_line(
            tenant,
            property_,
            room_type,
            stay,
            guest_email="worker@example.com",
            key_prefix="race1",
        )
        task = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=line.id,
            idempotency_key="race1-checkout",
        )
        task = HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=task.id,
            idempotency_key="race1-start",
        )
        assert task.status == TaskStatus.IN_PROGRESS

        results: dict[str, tuple[object, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)
                outcome = HousekeepingService.complete_cleaning(
                    tenant_id=tenant.id,
                    task_id=task.id,
                    idempotency_key=idempotency_key,
                )
                results[caller] = (outcome, None)
            except Exception as exc:  # noqa: BLE001 — captured for assertion
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_attempt, args=("A", "race1-complete-A"))
        thread_b = threading.Thread(target=_attempt, args=("B", "race1-complete-B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (out, exc) in results.items() if exc is None]
        failures = [(c, exc) for c, (out, exc) in results.items() if exc is not None]
        assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
        assert len(failures) == 1, f"expected exactly one loser, got {results!r}"

        loser, loser_exc = failures[0]
        assert isinstance(loser_exc, ConcurrencyError), (
            f"loser must fail with ConcurrencyError, got {loser_exc!r}"
        )

        task.refresh_from_db()
        assert task.status == TaskStatus.QUALITY_CHECK  # transitioned exactly once
        rooms[0].refresh_from_db()
        assert rooms[0].operational_state == Room.OperationalState.INSPECTED  # exactly once


class TestDuplicateDepartureTaskRace:
    """Test 2: two checkout/task-creation calls for the same room/date."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_task_survives(self):
        tenant, property_, room_type, rooms, stay = _bootstrap(room_count=1)
        line = _checked_in_line(
            tenant,
            property_,
            room_type,
            stay,
            guest_email="dup@example.com",
            key_prefix="race2",
        )

        results: dict[str, tuple[object, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)
                outcome = HousekeepingService.check_out_and_create_task(
                    tenant_id=tenant.id,
                    booking_line_id=line.id,
                    idempotency_key=idempotency_key,
                )
                results[caller] = (outcome, None)
            except Exception as exc:  # noqa: BLE001
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_attempt, args=("A", "race2-checkout-A"))
        thread_b = threading.Thread(target=_attempt, args=("B", "race2-checkout-B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (out, exc) in results.items() if exc is None]
        # Exactly one HousekeepingTask row for this room/date/kind, regardless
        # of whether the loser failed on the BookingLine guard or a DB
        # constraint — the UniqueConstraint is the ultimate backstop.
        assert HousekeepingTask.objects.filter(tenant=tenant).count() == 1
        assert len(successes) >= 1


class TestHousekeepingVsAllocationRace:
    """Test 3: Housekeeping's inspect(pass) races Allocation's allocate_line
    on the same room — the room is never left in a corrupted/ambiguous state."""

    @pytest.mark.django_db(transaction=True)
    def test_no_corruption_either_outcome_is_valid(self):
        tenant, property_, room_type, rooms, stay = _bootstrap(room_count=1)
        room = rooms[0]

        first_line = _checked_in_line(
            tenant,
            property_,
            room_type,
            stay,
            guest_email="first@example.com",
            key_prefix="race3a",
        )
        task = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=first_line.id,
            idempotency_key="race3-checkout",
        )
        task = HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=task.id,
            idempotency_key="race3-start",
        )
        task = HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=task.id,
            idempotency_key="race3-complete",
        )
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.INSPECTED

        # A second, independent reservation/booking needs a room of the
        # same type — this is what Allocation will try to grab concurrently.
        second_line_request = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=GuestCount(adults=1, children=0),
            quantity=1,
        )
        second_reservation = ReservationService.reserve(
            tenant=tenant,
            property=property_,
            lines=[second_line_request],
            idempotency_key="race3b-reserve",
            guest_email="second@example.com",
        )
        ReservationService.request_payment(second_reservation.id, tenant_id=second_reservation.tenant_id)
        second_booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=second_reservation.id,
            idempotency_key="race3b-confirm",
        )
        second_line = second_booking.lines.get()

        results: dict[str, tuple[object, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _inspect() -> None:
            try:
                barrier.wait(timeout=10)
                outcome = HousekeepingService.inspect(
                    tenant_id=tenant.id,
                    task_id=task.id,
                    result="pass",
                    idempotency_key="race3-inspect",
                )
                results["inspect"] = (outcome, None)
            except Exception as exc:  # noqa: BLE001
                results["inspect"] = (None, exc)
            finally:
                connection.close()

        def _allocate() -> None:
            try:
                barrier.wait(timeout=10)
                outcome = AllocationService.allocate_line(
                    tenant_id=tenant.id,
                    booking_line_id=second_line.id,
                    idempotency_key="race3-allocate",
                )
                results["allocate"] = (outcome, None)
            except Exception as exc:  # noqa: BLE001
                results["allocate"] = (None, exc)
            finally:
                connection.close()

        thread_inspect = threading.Thread(target=_inspect)
        thread_allocate = threading.Thread(target=_allocate)
        thread_inspect.start()
        thread_allocate.start()
        thread_inspect.join(timeout=15)
        thread_allocate.join(timeout=15)

        assert set(results) == {"inspect", "allocate"}
        inspect_outcome, inspect_exc = results["inspect"]
        allocate_outcome, allocate_exc = results["allocate"]

        # Housekeeping's own transition must always succeed independently —
        # allocation never blocks or corrupts it.
        assert inspect_exc is None, f"inspect() must not fail, got {inspect_exc!r}"

        room.refresh_from_db()
        second_line.refresh_from_db()

        # Baseline: the FIRST line's own allocation (during setup) already
        # created one AllocationRecord for this room, before the race began.
        if allocate_exc is None:
            # Allocation won the race AFTER inspection made the room
            # available — legitimate, sequential outcome.
            assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN
            assert second_line.room_id == room.id
            assert AllocationRecord.objects.filter(room=room).count() == 2
            assert AllocationRecord.objects.filter(room=room, booking_line=second_line).count() == 1
        else:
            # Allocation ran before (or raced past) the room becoming
            # available — a clean, non-corrupting rejection.
            assert isinstance(allocate_exc, NoEligibleRoom)
            assert room.operational_state == Room.OperationalState.VACANT_CLEAN
            assert second_line.room_id is None
            assert AllocationRecord.objects.filter(room=room).count() == 1
            assert AllocationRecord.objects.filter(room=room, booking_line=second_line).count() == 0


class TestFailureRollsBackEverything:
    """Test 4: a forced failure after the Room transition but before the
    task transition commits must leave no partial state."""

    @pytest.mark.django_db(transaction=True)
    def test_failure_after_room_transition_rolls_back_everything(self, monkeypatch):
        tenant, property_, room_type, rooms, stay = _bootstrap(room_count=1)
        line = _checked_in_line(
            tenant,
            property_,
            room_type,
            stay,
            guest_email="fail@example.com",
            key_prefix="race4",
        )
        task = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=line.id,
            idempotency_key="race4-checkout",
        )
        room = rooms[0]

        from apps.shared.workflows.runner import WorkflowRunner

        original_run = WorkflowRunner.run
        call_count = {"n": 0}

        def _flaky_run(self, name, **kwargs):
            # Let Room's own "clean" transition succeed, then blow up on the
            # HousekeepingTask's "start_cleaning" transition right after —
            # simulating a failure between the Room change and the task
            # change committing.
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated failure before task transition")
            return original_run(self, name, **kwargs)

        monkeypatch.setattr(WorkflowRunner, "run", _flaky_run)

        with pytest.raises(RuntimeError):
            HousekeepingService.start_cleaning(
                tenant_id=tenant.id,
                task_id=task.id,
                idempotency_key="race4-start",
            )

        room.refresh_from_db()
        task.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_DIRTY  # rolled back
        assert task.status == TaskStatus.PLANNED  # rolled back


class TestIdempotentReplay:
    """Test 5: same idempotency key replay across the whole pipeline."""

    @pytest.mark.django_db(transaction=True)
    def test_replay_never_double_transitions_or_duplicates(self):
        tenant, property_, room_type, rooms, stay = _bootstrap(room_count=1)
        line = _checked_in_line(
            tenant,
            property_,
            room_type,
            stay,
            guest_email="replay@example.com",
            key_prefix="race5",
        )
        room = rooms[0]

        task_a = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=line.id,
            idempotency_key="race5-checkout",
        )
        task_b = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=line.id,
            idempotency_key="race5-checkout",
        )
        assert task_a.id == task_b.id
        assert HousekeepingTask.objects.filter(room=room).count() == 1

        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=task_a.id,
            idempotency_key="race5-start",
        )
        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=task_a.id,
            idempotency_key="race5-start",
        )
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.CLEANING  # not double-transitioned

        HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=task_a.id,
            idempotency_key="race5-complete",
        )
        HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=task_a.id,
            idempotency_key="race5-complete",
        )
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.INSPECTED

        HousekeepingService.inspect(
            tenant_id=tenant.id,
            task_id=task_a.id,
            result="pass",
            idempotency_key="race5-inspect",
        )
        HousekeepingService.inspect(
            tenant_id=tenant.id,
            task_id=task_a.id,
            result="pass",
            idempotency_key="race5-inspect",
        )
        room.refresh_from_db()
        task_a.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN
        assert task_a.status == TaskStatus.VERIFIED
        assert Inspection.objects.filter(housekeeping_task=task_a).count() == 1
