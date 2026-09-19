"""BookingService unit tests (M9).

Unit tier: SQLite. The pessimistic-locking/row-race proof is Postgres-only
(tests/integration/test_bookings_postgres.py) — this tier proves the
composition, snapshot, fan-out, and idempotency behavior.
"""

import pytest

from apps.availability.services import AvailabilityQuery
from apps.bookings.models import Booking, BookingLine, BookingStatus
from apps.bookings.services import BookingQuery, BookingService
from apps.reservations.models import ReservationStatus
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.value_objects import DateRange, GuestCount


@pytest.mark.django_db
class TestConfirm:
    def test_creates_a_confirmed_booking(self, tenant, awaiting_payment_reservation):
        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="c-1",
        )
        assert booking.aggregate_status == BookingStatus.CONFIRMED
        assert booking.booking_ref
        assert booking.reservation_id == awaiting_payment_reservation.id

    def test_requires_awaiting_payment(self, tenant, property, room_type, stay):
        line = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=GuestCount(adults=1, children=0),
            quantity=1,
        )
        held_reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line],
            idempotency_key="held-1",
            guest_email="held@example.com",
        )
        assert held_reservation.status == ReservationStatus.HELD
        with pytest.raises(TransitionNotAllowed):
            BookingService.confirm(
                tenant_id=tenant.id,
                reservation_id=held_reservation.id,
                idempotency_key="c-held",
            )
        assert Booking.objects.count() == 0

    def test_converts_reservation_and_sells_inventory(
        self, tenant, property, room_type, stay, awaiting_payment_reservation
    ):
        BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="c-2",
        )
        awaiting_payment_reservation.refresh_from_db()
        assert awaiting_payment_reservation.status == ReservationStatus.CONVERTED

        dr = DateRange(stay.arrival, stay.departure)
        remaining = AvailabilityQuery.remaining_for_range(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
        )
        assert all(r == 4 for r in remaining.values())  # 5 - 1 sold

    def test_copies_price_and_policy_snapshots_verbatim(self, tenant, awaiting_payment_reservation):
        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="c-3",
        )
        assert booking.price_snapshot == awaiting_payment_reservation.price_snapshot
        assert booking.policy_snapshot == awaiting_payment_reservation.policy_snapshot
        assert booking.currency == awaiting_payment_reservation.price_snapshot["currency"]
        assert (
            booking.total_minor_units
            == awaiting_payment_reservation.price_snapshot["total_minor_units"]
        )

    def test_guest_snapshot_captured_without_calling_guest_service(
        self, monkeypatch, tenant, awaiting_payment_reservation
    ):
        from apps.guests.services import GuestService

        def _boom(*args, **kwargs):
            raise AssertionError("confirm() must not call GuestService")

        monkeypatch.setattr(GuestService, "resolve", _boom)

        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="c-4",
        )
        assert booking.guest_snapshot["email"] == "guest@example.com"
        assert booking.guest_profile_id == awaiting_payment_reservation.guest_profile_id

    def test_line_fan_out_by_quantity(self, tenant, property, room_type, stay):
        line = ReservationLineRequest(
            room_type_id=room_type.id,
            stay_period=stay,
            guest_count=GuestCount(adults=2, children=0),
            quantity=3,
        )
        reservation = ReservationService.reserve(
            tenant=tenant,
            property=property,
            lines=[line],
            idempotency_key="fanout-1",
            guest_email="fanout@example.com",
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)

        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="c-fanout",
        )
        lines = list(BookingLine.objects.filter(booking=booking).order_by("line_no"))
        assert len(lines) == 3
        assert [line.line_no for line in lines] == [1, 2, 3]
        assert all(line.status == BookingStatus.CONFIRMED for line in lines)
        assert all(line.room_id is None for line in lines)
        assert all(line.room_type_id == room_type.id for line in lines)
        assert all(line.arrival_date == stay.arrival for line in lines)
        assert all(line.price_snapshot == lines[0].price_snapshot for line in lines)

    def test_is_idempotent_per_key(self, tenant, awaiting_payment_reservation):
        first = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="same-key",
        )
        second = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="same-key",
        )
        assert first.id == second.id
        assert Booking.objects.count() == 1

    def test_second_confirm_with_different_key_raises_and_creates_nothing(
        self, tenant, awaiting_payment_reservation
    ):
        BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="first-key",
        )
        with pytest.raises(TransitionNotAllowed):
            BookingService.confirm(
                tenant_id=tenant.id,
                reservation_id=awaiting_payment_reservation.id,
                idempotency_key="second-key",
            )
        assert Booking.objects.count() == 1  # only the first confirm's booking

    def test_unique_reservation_constraint_at_db_level(self, tenant, awaiting_payment_reservation):
        """Direct ORM bypass — only the DB constraint can catch a duplicate
        Booking targeting the same reservation."""
        from django.db import IntegrityError

        from apps.bookings.models import Booking as BookingModel

        BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="uq-1",
        )
        with pytest.raises(IntegrityError):
            BookingModel.objects.create(
                tenant=tenant,
                property=awaiting_payment_reservation.property,
                reservation=awaiting_payment_reservation,
                booking_ref="DUPLICATE",
                aggregate_status=BookingStatus.PENDING_PAYMENT,
                currency="USD",
                total_minor_units=1000,
                arrival_date=awaiting_payment_reservation.lines.first().arrival_date,
                departure_date=awaiting_payment_reservation.lines.first().departure_date,
            )


@pytest.mark.django_db
class TestBookingQuery:
    def test_by_booking_ref(self, tenant, awaiting_payment_reservation):
        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="q-1",
        )
        assert BookingQuery.by_booking_ref(tenant, booking.booking_ref) == booking

    def test_by_reservation(self, tenant, awaiting_payment_reservation):
        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="q-2",
        )
        assert BookingQuery.by_reservation(awaiting_payment_reservation) == booking

    def test_arrivals_for_property(self, tenant, property, awaiting_payment_reservation, stay):
        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=awaiting_payment_reservation.id,
            idempotency_key="q-3",
        )
        arrivals = BookingQuery.arrivals_for_property(property, stay.arrival)
        assert list(arrivals) == list(BookingLine.objects.filter(booking=booking))
