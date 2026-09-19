"""Reservation state-machine transition matrix (M8, SDD S9.3).

Exercises the declared edges directly via WorkflowRunner — mirrors
tests/unit/rooms/test_state_machine.py's approach for Room.
"""

import pytest

from apps.reservations.models import Reservation, ReservationStatus
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.workflows.runner import WorkflowRunner


@pytest.fixture
def reservation(tenant, property):
    return Reservation.objects.create(
        tenant=tenant,
        property=property,
        reservation_ref="SMTEST",
        status=ReservationStatus.DRAFT,
    )


@pytest.mark.django_db
class TestValidTransitions:
    def test_draft_to_held(self, reservation):
        updated = WorkflowRunner(reservation, field="status").run("hold")
        assert updated.status == ReservationStatus.HELD

    def test_held_to_awaiting_payment(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        updated = WorkflowRunner(reservation, field="status").run("request_payment")
        assert updated.status == ReservationStatus.AWAITING_PAYMENT

    def test_held_to_expired(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        updated = WorkflowRunner(reservation, field="status").run("expire")
        assert updated.status == ReservationStatus.EXPIRED

    def test_awaiting_payment_to_expired(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("request_payment")
        updated = WorkflowRunner(reservation, field="status").run("expire")
        assert updated.status == ReservationStatus.EXPIRED

    def test_held_to_cancelled(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        updated = WorkflowRunner(reservation, field="status").run("cancel")
        assert updated.status == ReservationStatus.CANCELLED

    def test_awaiting_payment_to_cancelled(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("request_payment")
        updated = WorkflowRunner(reservation, field="status").run("cancel")
        assert updated.status == ReservationStatus.CANCELLED

    def test_draft_to_cancelled(self, reservation):
        updated = WorkflowRunner(reservation, field="status").run("cancel")
        assert updated.status == ReservationStatus.CANCELLED

    def test_awaiting_payment_to_converted(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("request_payment")
        updated = WorkflowRunner(reservation, field="status").run("convert")
        assert updated.status == ReservationStatus.CONVERTED


@pytest.mark.django_db
class TestForbiddenTransitions:
    def test_draft_to_awaiting_payment_is_not_allowed(self, reservation):
        with pytest.raises(TransitionNotAllowed):
            WorkflowRunner(reservation, field="status").run("request_payment")

    def test_draft_to_converted_is_not_allowed(self, reservation):
        with pytest.raises(TransitionNotAllowed):
            WorkflowRunner(reservation, field="status").run("convert")

    def test_held_to_converted_is_not_allowed(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        with pytest.raises(TransitionNotAllowed):
            WorkflowRunner(reservation, field="status").run("convert")

    def test_converted_is_terminal(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("request_payment")
        WorkflowRunner(reservation, field="status").run("convert")
        for name in ("hold", "request_payment", "expire", "cancel", "convert"):
            with pytest.raises(TransitionNotAllowed):
                WorkflowRunner(reservation, field="status").run(name)

    def test_expired_is_terminal(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("expire")
        for name in ("hold", "request_payment", "expire", "cancel", "convert"):
            with pytest.raises(TransitionNotAllowed):
                WorkflowRunner(reservation, field="status").run(name)

    def test_cancelled_is_terminal(self, reservation):
        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("cancel")
        for name in ("hold", "request_payment", "expire", "cancel", "convert"):
            with pytest.raises(TransitionNotAllowed):
                WorkflowRunner(reservation, field="status").run(name)


@pytest.mark.django_db
class TestEventEmission:
    def test_hold_emits_reservation_created(self, reservation):
        from apps.shared.models import OutboxEvent

        WorkflowRunner(reservation, field="status").run("hold")
        assert OutboxEvent.objects.filter(
            event_type="reservation.created", aggregate_id=str(reservation.pk)
        ).exists()

    def test_expire_emits_reservation_expired(self, reservation):
        from apps.shared.models import OutboxEvent

        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("expire")
        assert OutboxEvent.objects.filter(
            event_type="reservation.expired", aggregate_id=str(reservation.pk)
        ).exists()

    def test_convert_emits_reservation_converted(self, reservation):
        from apps.shared.models import OutboxEvent

        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("request_payment")
        WorkflowRunner(reservation, field="status").run("convert")
        assert OutboxEvent.objects.filter(
            event_type="reservation.converted", aggregate_id=str(reservation.pk)
        ).exists()

    def test_cancel_does_not_emit_any_event(self, reservation):
        """M8 ruling: no reservation.cancelled event added to the catalog."""
        from apps.shared.models import OutboxEvent

        WorkflowRunner(reservation, field="status").run("hold")
        WorkflowRunner(reservation, field="status").run("cancel")
        assert (
            not OutboxEvent.objects.filter(aggregate_id=str(reservation.pk))
            .filter(event_type__icontains="cancel")
            .exists()
        )
