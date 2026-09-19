"""NotificationProjector unit tests (M13).

Consumes the REAL events M8/M9/M11 already emit, relayed through the
existing ``OutboxRelay`` (M1.3) — exactly as production would.
"""

import pytest
from django.db import IntegrityError
from tests.unit.notifications.conftest import make_reservation

from apps.allocation.services import AllocationService
from apps.bookings.services import BookingService
from apps.notifications.models import (
    ChannelPreference,
    NotificationJob,
    NotificationTemplate,
    TemplateStatus,
)
from apps.notifications.projectors import NOTIFIABLE_EVENT_TYPES, NotificationProjector
from apps.rooms.models import Room
from apps.shared.services.outbox import OutboxRelay


@pytest.mark.django_db
class TestNotifiableEventTypes:
    def test_hk_events_are_excluded(self):
        """M13 ruling: hk.task_completed/hk.defect_reported are NOT
        Notification consumers in the frozen event catalog."""
        assert "hk.task_completed" not in NOTIFIABLE_EVENT_TYPES
        assert "hk.defect_reported" not in NOTIFIABLE_EVENT_TYPES

    def test_the_five_approved_events_are_included(self):
        assert set(NOTIFIABLE_EVENT_TYPES) == {
            "reservation.created",
            "reservation.expired",
            "reservation.converted",
            "booking.confirmed",
            "room.allocated",
        }


@pytest.mark.django_db
class TestEventToJobMapping:
    def test_reservation_created_produces_one_job(self, tenant, property, room_type, stay):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="a@example.com",
            key_prefix="p1",
        )
        processed = NotificationProjector.process_batch()
        assert processed == 1
        job = NotificationJob.objects.get()
        assert job.notification_type == "reservation_created"
        assert job.channel == "email"
        assert job.context["guest_name"]
        assert job.context["reservation_ref"]

    def test_reservation_expired_produces_a_job(self, tenant, property, room_type, stay):
        from apps.reservations.services import ReservationService

        reservation = make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="b@example.com",
            key_prefix="p2",
        )
        ReservationService.expire(reservation.id)
        OutboxRelay().publish_batch()
        NotificationProjector.process_batch()
        assert NotificationJob.objects.filter(notification_type="reservation_expired").exists()

    def test_reservation_converted_and_booking_confirmed_and_room_allocated(
        self, tenant, property, room_type, stay
    ):
        from apps.reservations.services import ReservationService

        reservation = make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="c@example.com",
            key_prefix="p3",
        )
        ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
        booking = BookingService.confirm(
            tenant_id=tenant.id,
            reservation_id=reservation.id,
            idempotency_key="p3-confirm",
        )
        Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        booking_line = booking.lines.get()
        AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=booking_line.id,
            idempotency_key="p3-allocate",
        )
        OutboxRelay().publish_batch()
        NotificationProjector.process_batch()

        types = set(NotificationJob.objects.values_list("notification_type", flat=True))
        assert {
            "reservation_created",
            "reservation_converted",
            "booking_confirmed",
            "room_allocated",
        } <= types
        allocated_job = NotificationJob.objects.get(notification_type="room_allocated")
        assert allocated_job.context["room_code"] == "101"
        assert allocated_job.context["booking_ref"] == booking.booking_ref

    def test_replay_of_already_processed_event_is_a_no_op(self, tenant, property, room_type, stay):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="d@example.com",
            key_prefix="p4",
        )
        NotificationProjector.process_batch()
        assert NotificationJob.objects.count() == 1
        processed_again = NotificationProjector.process_batch()
        assert processed_again == 0
        assert NotificationJob.objects.count() == 1


@pytest.mark.django_db
class TestSuppression:
    def test_suppressed_channel_creates_no_job(self, tenant, property, room_type, stay):
        reservation = make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="e@example.com",
            key_prefix="p5",
        )
        ChannelPreference.objects.create(
            tenant=tenant,
            guest_profile=reservation.guest_profile,
            channel="email",
            suppressed=True,
        )
        NotificationProjector.process_batch()
        assert NotificationJob.objects.count() == 0


@pytest.mark.django_db
class TestTemplateResolution:
    def test_job_pins_the_published_template(
        self, tenant, property, room_type, stay, reservation_created_template
    ):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="f@example.com",
            key_prefix="p6",
        )
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get()
        assert job.template_id == reservation_created_template.id

    def test_missing_template_still_creates_the_job(self, tenant, property, room_type, stay):
        """DMS invariant #1: "a notification is never lost" — an unresolved
        template does not stop the job from being created; it fails cleanly
        at delivery time instead (see test_services.py)."""
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="g@example.com",
            key_prefix="p7",
        )
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get()
        assert job.template_id is None

    def test_draft_template_is_not_resolved(self, tenant, property, room_type, stay):
        NotificationTemplate.objects.create(
            tenant=tenant,
            notification_type="reservation_created",
            channel="email",
            locale="en",
            subject="x",
            body="y",
            status=TemplateStatus.DRAFT,
        )
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="h@example.com",
            key_prefix="p8",
        )
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get()
        assert job.template_id is None


@pytest.mark.django_db
class TestDuplicateJobConstraint:
    def test_unique_source_event_channel_at_db_level(self, tenant, property, room_type, stay):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="i@example.com",
            key_prefix="p9",
        )
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get()
        with pytest.raises(IntegrityError):
            NotificationJob.objects.create(
                tenant=tenant,
                source_event=job.source_event,
                recipient_guest=job.recipient_guest,
                notification_type=job.notification_type,
                channel="email",
            )
