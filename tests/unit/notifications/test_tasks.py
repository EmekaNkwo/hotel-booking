"""Celery task unit tests (M13). ``CELERY_TASK_ALWAYS_EAGER=True`` in the
test settings runs ``.delay()`` synchronously in-process — no broker needed.
"""

import pytest
from tests.unit.notifications.conftest import make_reservation

from apps.notifications.models import JobStatus, NotificationJob
from apps.notifications.projectors import NotificationProjector
from apps.notifications.tasks import deliver_notification_job, dispatch_notifications


@pytest.mark.django_db
class TestDeliverNotificationJobTask:
    def test_delivers_a_pending_job(
        self, tenant, property, room_type, stay, reservation_created_template
    ):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="task@example.com",
            key_prefix="t1",
        )
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get()

        result = deliver_notification_job.run(job.id)
        job.refresh_from_db()
        assert job.status == JobStatus.DELIVERED
        assert result == JobStatus.DELIVERED


@pytest.mark.django_db
class TestDispatchNotificationsTask:
    def test_processes_events_and_enqueues_delivery(
        self, tenant, property, room_type, stay, reservation_created_template
    ):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="dispatch@example.com",
            key_prefix="t2",
        )
        enqueued = dispatch_notifications()
        assert enqueued == 1
        job = NotificationJob.objects.get()
        # CELERY_TASK_ALWAYS_EAGER ran delivery synchronously as part of dispatch.
        assert job.status == JobStatus.DELIVERED

    def test_is_safe_to_run_repeatedly(
        self, tenant, property, room_type, stay, reservation_created_template
    ):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="repeat@example.com",
            key_prefix="t3",
        )
        dispatch_notifications()
        second = dispatch_notifications()
        assert second == 0  # nothing new to dispatch — already delivered
        assert NotificationJob.objects.count() == 1
