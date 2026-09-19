"""Postgres integration tests — Booking confirmation concurrency proofs (M9).

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_reservations_postgres.py``/
``test_availability_postgres.py``.

Two real, independent connections/transactions (Django opens one connection
per OS thread lazily — no mocking of concurrency), the same shape as the M7/M8
race proofs.
"""

import threading
from datetime import date, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.availability.models import AvailabilitySlot
from apps.availability.services import AvailabilityService
from apps.bookings.models import Booking, BookingLine
from apps.bookings.services import BookingService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.properties.models import Property
from apps.reservations.models import ReservationStatus
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import RoomType
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.value_objects import GuestCount, StayPeriod
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="real concurrent connections require Postgres"
)


def _bootstrap_awaiting_payment(*, total_units: int, quantity: int = 1, nights: int = 2):
    tenant = Tenant.objects.create(
        code=f"bk{timezone.now().timestamp()}", name="Booking Race", base_currency="NGN"
    )
    property_ = Property.objects.create(
        tenant=tenant,
        code="BK1",
        name="Booking Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
    )
    room_type = RoomType.objects.create(
        tenant=tenant,
        code="BK-KING",
        name="Booking King",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
    )
    rate_plan = PricingService.create_rate_plan(
        tenant=tenant,
        property=property_,
        room_type=room_type,
        code="BK-RACK",
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
        total_units=total_units,
        start_date=today,
        horizon_days=nights,
    )
    stay = StayPeriod(today, today + timedelta(days=nights))
    line = ReservationLineRequest(
        room_type_id=room_type.id,
        stay_period=stay,
        guest_count=GuestCount(adults=1, children=0),
        quantity=quantity,
    )
    reservation = ReservationService.reserve(
        tenant=tenant,
        property=property_,
        lines=[line],
        idempotency_key="bootstrap-reserve",
        guest_email="racer@example.com",
    )
    ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
    reservation.refresh_from_db()
    return tenant, property_, room_type, reservation, stay


class TestConcurrentConfirmRace:
    """Two real connections confirming the SAME reservation, distinct keys."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_confirm_wins(self):
        tenant, property_, room_type, reservation, stay = _bootstrap_awaiting_payment(
            total_units=5, quantity=2, nights=2
        )

        results: dict[str, tuple[Booking | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)
                booking = BookingService.confirm(
                    tenant_id=tenant.id,
                    reservation_id=reservation.id,
                    idempotency_key=idempotency_key,
                )
                results[caller] = (booking, None)
            except Exception as exc:  # noqa: BLE001 — captured for assertion
                results[caller] = (None, exc)
            finally:
                connection.close()

        thread_a = threading.Thread(target=_attempt, args=("A", "confirm-race-key-A"))
        thread_b = threading.Thread(target=_attempt, args=("B", "confirm-race-key-B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (bk, exc) in results.items() if exc is None]
        failures = [(c, exc) for c, (bk, exc) in results.items() if exc is not None]
        assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
        assert len(failures) == 1, f"expected exactly one loser, got {results!r}"

        loser, loser_exc = failures[0]
        assert isinstance(loser_exc, TransitionNotAllowed), (
            f"loser must fail with TransitionNotAllowed, got {loser_exc!r}"
        )

        # Exactly one Booking, exactly one Reservation conversion.
        assert Booking.objects.filter(tenant=tenant).count() == 1
        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.CONVERTED

        # Loser created zero Booking/BookingLine rows.
        winner_booking = Booking.objects.get(tenant=tenant)
        assert BookingLine.objects.filter(booking__tenant=tenant).count() == 2  # quantity=2 fan-out
        assert BookingLine.objects.filter(booking=winner_booking).count() == 2

        # Inventory sold exactly once; reserved == 0; no negative/duplicated units.
        slots = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
        ).order_by("business_date")
        assert [s.sold for s in slots] == [2, 2]
        assert [s.reserved for s in slots] == [0, 0]
        assert [s.remaining for s in slots] == [3, 3]  # 5 - 2

    @pytest.mark.django_db(transaction=True)
    def test_same_key_replay_returns_same_booking_no_second_conversion(self):
        tenant, property_, room_type, reservation, stay = _bootstrap_awaiting_payment(
            total_units=3, quantity=1, nights=1
        )

        first = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="replay-key",
        )
        second = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="replay-key",
        )

        assert first.id == second.id
        assert Booking.objects.filter(tenant=tenant).count() == 1

        slots = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
        )
        assert [s.sold for s in slots] == [1]  # not double-converted
        assert [s.reserved for s in slots] == [0]
