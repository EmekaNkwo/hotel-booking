"""Reservation/ReservationLine constraint tests — the DB-level backstop (M8)."""

from datetime import date, timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.reservations.models import Reservation, ReservationLine, ReservationStatus


@pytest.mark.django_db
class TestReservationConstraints:
    def test_unique_reservation_ref_per_tenant(self, tenant, property):
        Reservation.objects.create(
            tenant=tenant,
            property=property,
            reservation_ref="ABC123",
            status=ReservationStatus.DRAFT,
        )
        with pytest.raises(IntegrityError):
            Reservation.objects.create(
                tenant=tenant,
                property=property,
                reservation_ref="ABC123",
                status=ReservationStatus.DRAFT,
            )

    def test_hold_expiry_must_be_after_created_at(self, tenant, property):
        with pytest.raises(IntegrityError):
            Reservation.objects.create(
                tenant=tenant,
                property=property,
                reservation_ref="BADEXP",
                status=ReservationStatus.HELD,
                hold_expiry_at=timezone.now() - timedelta(days=1),
            )

    def test_null_hold_expiry_is_allowed(self, tenant, property):
        reservation = Reservation.objects.create(
            tenant=tenant,
            property=property,
            reservation_ref="NOEXP",
            status=ReservationStatus.DRAFT,
            hold_expiry_at=None,
        )
        assert reservation.hold_expiry_at is None


@pytest.mark.django_db
class TestReservationWorkflowStateGuard:
    """R0.6 regression: ``status`` is WorkflowRunner-governed —
    ``WorkflowStateGuardMixin`` must reject a direct save() bypass, the
    same protection ``Room.operational_state`` has had since M3."""

    def test_direct_status_mutation_is_rejected(self, tenant, property):
        reservation = Reservation.objects.create(
            tenant=tenant,
            property=property,
            reservation_ref="GUARD1",
            status=ReservationStatus.HELD,
        )
        reservation.status = ReservationStatus.CONVERTED
        with pytest.raises(ValueError, match="WorkflowRunner"):
            reservation.save()
        reservation.refresh_from_db()
        assert reservation.status == ReservationStatus.HELD

    def test_saving_unrelated_fields_without_a_status_change_is_allowed(self, tenant, property):
        """The guard only fires on an ACTUAL status change — saving other
        fields (or re-saving the same status) must not be blocked."""
        reservation = Reservation.objects.create(
            tenant=tenant,
            property=property,
            reservation_ref="GUARD2",
            status=ReservationStatus.HELD,
            channel="direct",
        )
        reservation.channel = "ota"
        reservation.save()  # no status change — must not raise
        reservation.refresh_from_db()
        assert reservation.channel == "ota"

    def test_workflowrunner_driven_transition_still_succeeds(self, tenant, property):
        """The guard must not block the legitimate path — a real
        WorkflowRunner transition still works exactly as before."""
        from apps.shared.workflows.runner import WorkflowRunner

        reservation = Reservation.objects.create(
            tenant=tenant,
            property=property,
            reservation_ref="GUARD3",
            status=ReservationStatus.HELD,
        )
        updated = WorkflowRunner(reservation, field="status").run(
            "request_payment", reason="test"
        )
        assert updated.status == ReservationStatus.AWAITING_PAYMENT


@pytest.mark.django_db
class TestReservationLineConstraints:
    def _reservation(self, tenant, property, ref):
        return Reservation.objects.create(
            tenant=tenant,
            property=property,
            reservation_ref=ref,
            status=ReservationStatus.DRAFT,
        )

    def test_departure_must_be_after_arrival(self, tenant, property, room_type):
        reservation = self._reservation(tenant, property, "LINE1")
        with pytest.raises(IntegrityError):
            ReservationLine.objects.create(
                reservation=reservation,
                line_no=1,
                room_type=room_type,
                arrival_date=date(2026, 10, 5),
                departure_date=date(2026, 10, 5),
                quantity=1,
            )

    def test_quantity_must_be_positive(self, tenant, property, room_type):
        reservation = self._reservation(tenant, property, "LINE2")
        with pytest.raises(IntegrityError):
            ReservationLine.objects.create(
                reservation=reservation,
                line_no=1,
                room_type=room_type,
                arrival_date=date(2026, 10, 5),
                departure_date=date(2026, 10, 6),
                quantity=0,
            )

    def test_unique_line_no_per_reservation(self, tenant, property, room_type):
        reservation = self._reservation(tenant, property, "LINE3")
        ReservationLine.objects.create(
            reservation=reservation,
            line_no=1,
            room_type=room_type,
            arrival_date=date(2026, 10, 5),
            departure_date=date(2026, 10, 6),
            quantity=1,
        )
        with pytest.raises(IntegrityError):
            ReservationLine.objects.create(
                reservation=reservation,
                line_no=1,
                room_type=room_type,
                arrival_date=date(2026, 11, 5),
                departure_date=date(2026, 11, 6),
                quantity=1,
            )
