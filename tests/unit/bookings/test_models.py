"""Booking/BookingLine constraint tests — the DB-level backstop (M9)."""

from datetime import date

import pytest
from django.db import IntegrityError

from apps.bookings.models import Booking, BookingLine, BookingStatus


@pytest.mark.django_db
class TestBookingConstraints:
    def _booking(self, tenant, property, ref, **overrides):
        fields = {
            "tenant": tenant,
            "property": property,
            "booking_ref": ref,
            "aggregate_status": BookingStatus.CONFIRMED,
            "currency": "USD",
            "total_minor_units": 1000,
            "arrival_date": date(2026, 10, 5),
            "departure_date": date(2026, 10, 7),
        }
        fields.update(overrides)
        return Booking.objects.create(**fields)

    def test_unique_booking_ref_per_tenant(self, tenant, property):
        self._booking(tenant, property, "REF1")
        with pytest.raises(IntegrityError):
            self._booking(tenant, property, "REF1")

    def test_total_must_be_non_negative(self, tenant, property):
        with pytest.raises(IntegrityError):
            self._booking(tenant, property, "REF2", total_minor_units=-1)

    def test_currency_must_be_iso3(self, tenant, property):
        with pytest.raises(IntegrityError):
            self._booking(tenant, property, "REF3", currency="US")

    def test_departure_must_be_after_arrival(self, tenant, property):
        with pytest.raises(IntegrityError):
            self._booking(
                tenant,
                property,
                "REF4",
                arrival_date=date(2026, 10, 5),
                departure_date=date(2026, 10, 5),
            )


@pytest.mark.django_db
class TestBookingLineConstraints:
    def _booking(self, tenant, property, ref):
        return Booking.objects.create(
            tenant=tenant,
            property=property,
            booking_ref=ref,
            aggregate_status=BookingStatus.CONFIRMED,
            currency="USD",
            total_minor_units=1000,
            arrival_date=date(2026, 10, 5),
            departure_date=date(2026, 10, 7),
        )

    def test_unique_line_no_per_booking(self, tenant, property, room_type):
        booking = self._booking(tenant, property, "LREF1")
        BookingLine.objects.create(
            booking=booking,
            line_no=1,
            room_type=room_type,
            arrival_date=date(2026, 10, 5),
            departure_date=date(2026, 10, 7),
            status=BookingStatus.CONFIRMED,
        )
        with pytest.raises(IntegrityError):
            BookingLine.objects.create(
                booking=booking,
                line_no=1,
                room_type=room_type,
                arrival_date=date(2026, 11, 5),
                departure_date=date(2026, 11, 7),
                status=BookingStatus.CONFIRMED,
            )

    def test_departure_must_be_after_arrival(self, tenant, property, room_type):
        booking = self._booking(tenant, property, "LREF2")
        with pytest.raises(IntegrityError):
            BookingLine.objects.create(
                booking=booking,
                line_no=1,
                room_type=room_type,
                arrival_date=date(2026, 10, 5),
                departure_date=date(2026, 10, 5),
                status=BookingStatus.CONFIRMED,
            )


@pytest.mark.django_db
class TestBookingWorkflowStateGuard:
    """R0.6 regression: ``aggregate_status`` is WorkflowRunner-governed —
    ``WorkflowStateGuardMixin`` must reject a direct save() bypass."""

    def _booking(self, tenant, property, ref, **overrides):
        fields = {
            "tenant": tenant,
            "property": property,
            "booking_ref": ref,
            "aggregate_status": BookingStatus.PENDING_PAYMENT,
            "currency": "USD",
            "total_minor_units": 1000,
            "arrival_date": date(2026, 10, 5),
            "departure_date": date(2026, 10, 7),
        }
        fields.update(overrides)
        return Booking.objects.create(**fields)

    def test_direct_status_mutation_is_rejected(self, tenant, property):
        booking = self._booking(tenant, property, "GUARDB1")
        booking.aggregate_status = BookingStatus.CONFIRMED
        with pytest.raises(ValueError, match="WorkflowRunner"):
            booking.save()
        booking.refresh_from_db()
        assert booking.aggregate_status == BookingStatus.PENDING_PAYMENT

    def test_saving_unrelated_fields_without_a_status_change_is_allowed(self, tenant, property):
        booking = self._booking(tenant, property, "GUARDB2")
        booking.total_minor_units = 2000
        booking.save()  # no status change — must not raise
        booking.refresh_from_db()
        assert booking.total_minor_units == 2000

    def test_workflowrunner_driven_transition_still_succeeds(self, tenant, property):
        from apps.shared.workflows.runner import WorkflowRunner

        booking = self._booking(tenant, property, "GUARDB3")
        updated = WorkflowRunner(booking, field="aggregate_status").run(
            "confirm", reason="test"
        )
        assert updated.aggregate_status == BookingStatus.CONFIRMED

    def test_booking_line_status_remains_a_plain_directly_mutable_field(
        self, tenant, property, room_type
    ):
        """The deliberate exception: BookingLine.status has no declared
        transitions and is NOT guarded — direct mutation must keep working
        exactly as Allocation/Housekeeping already rely on."""
        booking = self._booking(tenant, property, "GUARDB4")
        line = BookingLine.objects.create(
            booking=booking,
            line_no=1,
            room_type=room_type,
            arrival_date=date(2026, 10, 5),
            departure_date=date(2026, 10, 7),
            status=BookingStatus.CONFIRMED,
        )
        line.status = BookingStatus.CHECKED_IN
        line.save(update_fields=["status", "updated_at"])  # must not raise
        line.refresh_from_db()
        assert line.status == BookingStatus.CHECKED_IN
