"""Postgres integration tests — Allocation concurrency proofs (M11).

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_bookings_postgres.py``.

Two real, independent connections/transactions per race (Django opens one
connection per OS thread lazily — no mocking of concurrency), the same
shape as the M7/M8/M9 race proofs.
"""

import threading
from datetime import date, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.allocation.exceptions import BookingLineNotAllocatable, NoEligibleRoom
from apps.allocation.models import AllocationRecord
from apps.allocation.services import AllocationService
from apps.availability.services import AvailabilityService
from apps.bookings.models import BookingStatus
from apps.bookings.services import BookingService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.properties.models import Property
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import Room, RoomType
from apps.rooms.services import RoomStateMachine
from apps.shared.value_objects import GuestCount, StayPeriod
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="real concurrent connections require Postgres"
)


def _bootstrap(*, room_count: int, guest_emails: list[str] | None = None, nights: int = 2):
    """Tenant/property/room_type + N VACANT_CLEAN rooms + one CONFIRMED
    BookingLine per guest email, ready to allocate."""
    tenant = Tenant.objects.create(
        code=f"al{timezone.now().timestamp()}", name="Allocation Race", base_currency="NGN"
    )
    property_ = Property.objects.create(
        tenant=tenant,
        code="AL1",
        name="Allocation Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
    )
    room_type = RoomType.objects.create(
        tenant=tenant,
        code="AL-KING",
        name="Allocation King",
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
        code="AL-RACK",
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

    booking_lines = []
    for i, email in enumerate(guest_emails or []):
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
            idempotency_key=f"bootstrap-reserve-{i}",
            guest_email=email,
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key=f"bootstrap-confirm-{i}",
        )
        booking_lines.append(booking.lines.get())

    return tenant, property_, room_type, rooms, booking_lines


class TestConcurrentAllocationRace:
    """Test A: two different BookingLines, one VACANT_CLEAN room, racing."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_allocation_wins_the_only_room(self):
        tenant, property_, room_type, rooms, booking_lines = _bootstrap(
            room_count=1, guest_emails=["a@example.com", "b@example.com"]
        )
        line_a, line_b = booking_lines
        room = rooms[0]

        results: dict[str, tuple[AllocationRecord | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, booking_line_id: int, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)
                record = AllocationService.allocate_line(
                    tenant_id=tenant.id,
                    booking_line_id=booking_line_id,
                    idempotency_key=idempotency_key,
                )
                results[caller] = (record, None)
            except Exception as exc:  # noqa: BLE001 — captured for assertion
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_attempt, args=("A", line_a.id, "race-key-A"))
        thread_b = threading.Thread(target=_attempt, args=("B", line_b.id, "race-key-B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (rec, exc) in results.items() if exc is None]
        failures = [(c, exc) for c, (rec, exc) in results.items() if exc is not None]
        assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
        assert len(failures) == 1, f"expected exactly one loser, got {results!r}"

        loser, loser_exc = failures[0]
        assert isinstance(loser_exc, NoEligibleRoom), (
            f"loser must fail with NoEligibleRoom, got {loser_exc!r}"
        )

        assert AllocationRecord.objects.filter(tenant=tenant).count() == 1
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN

        winner = "A" if loser == "B" else "B"
        winner_line = line_a if winner == "A" else line_b
        loser_line = line_b if winner == "A" else line_a

        winner_line.refresh_from_db()
        loser_line.refresh_from_db()
        assert winner_line.room_id == room.id
        assert winner_line.status == BookingStatus.CHECKED_IN
        assert room.current_booking_line_id == winner_line.id

        assert loser_line.room_id is None
        assert loser_line.status == BookingStatus.CONFIRMED
        assert AllocationRecord.objects.filter(booking_line=loser_line).count() == 0


class TestCrossedPreferenceConcurrentAllocation:
    """R0.5 regression: two DIFFERENT guests, each with a stay-continuity
    preference for the OTHER's preferred room (crossed candidate order),
    racing to allocate concurrently. Before the fix, candidate ROOMS were
    locked in guest-specific score order, so two such allocations could
    lock two contested rooms in opposite orders — a real AB-BA deadlock.
    The fix locks in a fixed, guest-independent order (ascending room_id),
    so this must always resolve cleanly — never an unhandled exception."""

    @pytest.mark.django_db(transaction=True)
    def test_crossed_stay_continuity_preferences_resolve_without_deadlock(self):
        tenant, property_, room_type, rooms, booking_lines = _bootstrap(
            room_count=2, guest_emails=["cross-a@example.com", "cross-b@example.com"]
        )
        room1, room2 = sorted(rooms, key=lambda r: r.id)
        line_a, line_b = booking_lines

        # Give guest A a prior stay in room2 (the HIGHER id — opposite the
        # tie-break) by occupying room1 first, forcing allocation onto
        # room2, then cycling both back to vacant.
        RoomStateMachine.apply(room1, "allocate", reason="setup: force guest A into room2")
        record_a = AllocationService.allocate_line(
            tenant_id=tenant.id, booking_line_id=line_a.id, idempotency_key="setup-a"
        )
        assert record_a.room_id == room2.id
        room1.refresh_from_db()
        room2.refresh_from_db()
        for room in (room1, room2):
            RoomStateMachine.apply(room, "checkout")
            RoomStateMachine.apply(room, "clean")
            RoomStateMachine.apply(room, "complete_cleaning")
            RoomStateMachine.apply(room, "approve")

        # Give guest B a prior stay in room1 (the LOWER id) — the crossed,
        # opposite preference — by occupying room2 first this time.
        room2.refresh_from_db()
        RoomStateMachine.apply(room2, "allocate", reason="setup: force guest B into room1")
        record_b = AllocationService.allocate_line(
            tenant_id=tenant.id, booking_line_id=line_b.id, idempotency_key="setup-b"
        )
        assert record_b.room_id == room1.id
        room1.refresh_from_db()
        room2.refresh_from_db()
        for room in (room1, room2):
            RoomStateMachine.apply(room, "checkout")
            RoomStateMachine.apply(room, "clean")
            RoomStateMachine.apply(room, "complete_cleaning")
            RoomStateMachine.apply(room, "approve")

        # Fresh, unallocated lines for the SAME two guests — guest A's
        # candidate order is now [room2, room1] (continuity), guest B's is
        # [room1, room2] — genuinely crossed. Reuses _bootstrap()'s own
        # default 2-night window (the only one its horizon initialized);
        # physical-room availability is independent of the abstract
        # inventory unit count, so re-covering the same dates is fine.
        today = timezone.now().date()
        stay = StayPeriod(today, today + timedelta(days=2))
        race_lines = []
        for i, email in enumerate(["cross-a@example.com", "cross-b@example.com"]):
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
                idempotency_key=f"race-reserve-{i}",
                guest_email=email,
            )
            ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
            booking = BookingService.confirm(
                tenant_id=tenant.id,
                reservation_id=reservation.id,
                idempotency_key=f"race-confirm-{i}",
            )
            race_lines.append(booking.lines.get())
        race_line_a, race_line_b = race_lines

        results: dict[str, tuple[AllocationRecord | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, booking_line_id: int, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)
                record = AllocationService.allocate_line(
                    tenant_id=tenant.id,
                    booking_line_id=booking_line_id,
                    idempotency_key=idempotency_key,
                )
                results[caller] = (record, None)
            except (NoEligibleRoom, BookingLineNotAllocatable) as exc:
                # A clean, expected domain outcome under real contention —
                # never what this test is checking for.
                results[caller] = (None, exc)
            except Exception as exc:  # noqa: BLE001 — captured for assertion
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(
            target=_attempt, args=("A", race_line_a.id, "race-crossed-key-A")
        )
        thread_b = threading.Thread(
            target=_attempt, args=("B", race_line_b.id, "race-crossed-key-B")
        )
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        for caller, (_record, exc) in results.items():
            assert exc is None or isinstance(exc, NoEligibleRoom | BookingLineNotAllocatable), (
                f"caller {caller} raised an unexpected/unhandled exception "
                f"(e.g. a deadlock) instead of a clean domain outcome: {exc!r}"
            )

        # With 2 rooms and 2 non-conflicting lines, both must succeed.
        assert results["A"][1] is None and results["B"][1] is None
        record_a2, record_b2 = results["A"][0], results["B"][0]
        assert {record_a2.room_id, record_b2.room_id} == {room1.id, room2.id}
        # Preference is honored once serialized: A still prefers room2,
        # B still prefers room1 — no real contention, so both get their
        # continuity room.
        assert record_a2.room_id == room2.id
        assert record_b2.room_id == room1.id


class TestSameLineConcurrentAllocation:
    """Test B: same BookingLine, two concurrent calls, distinct keys."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_allocation_wins_same_line(self):
        tenant, property_, room_type, rooms, booking_lines = _bootstrap(
            room_count=2, guest_emails=["solo@example.com"]
        )
        (line,) = booking_lines

        results: dict[str, tuple[AllocationRecord | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)
                record = AllocationService.allocate_line(
                    tenant_id=tenant.id,
                    booking_line_id=line.id,
                    idempotency_key=idempotency_key,
                )
                results[caller] = (record, None)
            except Exception as exc:  # noqa: BLE001
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_attempt, args=("A", "same-line-key-A"))
        thread_b = threading.Thread(target=_attempt, args=("B", "same-line-key-B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (rec, exc) in results.items() if exc is None]
        failures = [(c, exc) for c, (rec, exc) in results.items() if exc is not None]
        assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
        assert len(failures) == 1, f"expected exactly one loser, got {results!r}"

        loser, loser_exc = failures[0]
        assert isinstance(loser_exc, BookingLineNotAllocatable), (
            f"loser must fail with BookingLineNotAllocatable, got {loser_exc!r}"
        )

        assert AllocationRecord.objects.filter(booking_line=line).count() == 1
        line.refresh_from_db()
        assert line.room_id is not None
        assert line.status == BookingStatus.CHECKED_IN


class TestIdempotentReplay:
    """Test C: same idempotency key replay."""

    @pytest.mark.django_db(transaction=True)
    def test_replay_returns_same_record_no_second_mutation(self):
        tenant, property_, room_type, rooms, booking_lines = _bootstrap(
            room_count=1, guest_emails=["replay@example.com"]
        )
        (line,) = booking_lines
        room = rooms[0]

        first = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=line.id,
            idempotency_key="replay-key",
        )
        second = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=line.id,
            idempotency_key="replay-key",
        )

        assert first.id == second.id
        assert AllocationRecord.objects.filter(booking_line=line).count() == 1
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN


class TestFailureRollsBackEverything:
    """Test D: a failure after room selection but before commit must leave
    no partial state — room, BookingLine, and AllocationRecord all roll back
    together (same outer transaction)."""

    @pytest.mark.django_db(transaction=True)
    def test_failure_after_room_state_change_rolls_back_everything(self, monkeypatch):
        tenant, property_, room_type, rooms, booking_lines = _bootstrap(
            room_count=1, guest_emails=["fail@example.com"]
        )
        (line,) = booking_lines
        room = rooms[0]

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated failure after room state change")

        # AllocationRecord.objects.create() runs AFTER RoomStateMachine.apply()
        # and the BookingLine save — forcing it to fail proves everything
        # earlier in the same transaction rolls back too.
        monkeypatch.setattr(AllocationRecord.objects, "create", _boom)

        with pytest.raises(RuntimeError):
            AllocationService.allocate_line(
                tenant_id=tenant.id,
                booking_line_id=line.id,
                idempotency_key="fail-key",
            )

        room.refresh_from_db()
        line.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN
        assert room.current_booking_line_id is None
        assert line.room_id is None
        assert line.status == BookingStatus.CONFIRMED
        assert AllocationRecord.objects.filter(booking_line=line).count() == 0
