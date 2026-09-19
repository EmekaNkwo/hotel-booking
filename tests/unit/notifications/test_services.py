"""NotificationService (delivery) unit tests (M13)."""

from datetime import timedelta

import pytest
from django.utils import timezone
from tests.unit.notifications.conftest import make_reservation

from apps.notifications.models import (
    AttemptStatus,
    DeliveryAttempt,
    JobStatus,
    NotificationJob,
)
from apps.notifications.projectors import NotificationProjector
from apps.notifications.providers import FakeEmailProvider
from apps.notifications.services import NotificationQuery, NotificationService
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.workflows.runner import WorkflowRunner


@pytest.fixture
def pending_job(tenant, property, room_type, stay, reservation_created_template):
    make_reservation(
        tenant, property, room_type, stay, guest_email="guest@example.com", key_prefix="j"
    )
    NotificationProjector.process_batch()
    return NotificationJob.objects.get()


@pytest.mark.django_db
class TestDeliverySuccess:
    def test_delivers_and_records_attempt(self, pending_job):
        provider = FakeEmailProvider()
        job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert job.status == JobStatus.DELIVERED
        attempt = DeliveryAttempt.objects.get(notification_job=job)
        assert attempt.status == AttemptStatus.SUCCEEDED
        assert attempt.provider_ref

    def test_renders_template_with_context(self, pending_job):
        provider = FakeEmailProvider()
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        sent = list(provider.sent_messages().values())[0]
        assert pending_job.context["reservation_ref"] in sent["subject"]

    def test_emits_notification_delivered(self, pending_job):
        from apps.shared.models import OutboxEvent

        job = NotificationService.deliver(job_id=pending_job.id, provider=FakeEmailProvider())
        assert OutboxEvent.objects.filter(
            event_type="notification.delivered", aggregate_id=str(job.pk)
        ).exists()

    def test_delivered_job_cannot_be_delivered_again(self, pending_job):
        provider = FakeEmailProvider()
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        with pytest.raises(TransitionNotAllowed):
            NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert DeliveryAttempt.objects.filter(notification_job=pending_job).count() == 1


@pytest.mark.django_db
class TestDeliveryFailureAndRetry:
    def test_provider_failure_marks_job_failed_and_increments_retry_count(self, pending_job):
        provider = FakeEmailProvider()
        key = NotificationService._idempotency_key(pending_job.id)
        provider.fail_next(key)
        job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert job.status == JobStatus.FAILED
        assert job.retry_count == 1
        assert job.last_error
        attempt = DeliveryAttempt.objects.get(notification_job=job)
        assert attempt.status == AttemptStatus.FAILED

    def test_notification_failed_not_emitted_on_a_plain_failure(self, pending_job):
        from apps.shared.models import OutboxEvent

        provider = FakeEmailProvider()
        provider.fail_next(NotificationService._idempotency_key(pending_job.id))
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert not OutboxEvent.objects.filter(event_type="notification.failed").exists()

    def test_retry_after_failure_succeeds(self, pending_job):
        """The FakeEmailProvider's fail_next() fails once then clears —
        the next deliver() call for the same job succeeds."""
        provider = FakeEmailProvider()
        key = NotificationService._idempotency_key(pending_job.id)
        provider.fail_next(key)
        job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert job.status == JobStatus.FAILED

        job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert job.status == JobStatus.DELIVERED

    def test_retry_ceiling_dead_letters(self, pending_job, settings):
        settings.NOTIFICATION_MAX_RETRIES = 2
        provider = FakeEmailProvider()
        key = NotificationService._idempotency_key(pending_job.id)

        for _ in range(2):
            provider.fail_next(key)
            job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
            assert job.status == JobStatus.FAILED

        job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert job.status == JobStatus.DEAD_LETTERED

    def test_notification_failed_emitted_only_on_dead_letter(self, pending_job, settings):
        from apps.shared.models import OutboxEvent

        settings.NOTIFICATION_MAX_RETRIES = 1
        provider = FakeEmailProvider()
        key = NotificationService._idempotency_key(pending_job.id)
        provider.fail_next(key)
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert not OutboxEvent.objects.filter(event_type="notification.failed").exists()

        job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert job.status == JobStatus.DEAD_LETTERED
        assert OutboxEvent.objects.filter(
            event_type="notification.failed", aggregate_id=str(job.pk)
        ).exists()

    def test_dead_lettered_job_cannot_be_delivered_again(self, pending_job, settings):
        settings.NOTIFICATION_MAX_RETRIES = 1
        provider = FakeEmailProvider()
        key = NotificationService._idempotency_key(pending_job.id)
        provider.fail_next(key)
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        job = NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert job.status == JobStatus.DEAD_LETTERED
        with pytest.raises(TransitionNotAllowed):
            NotificationService.deliver(job_id=pending_job.id, provider=provider)


@pytest.mark.django_db
class TestUnresolvedTemplateOrRecipient:
    def test_missing_template_fails_delivery_cleanly(self, tenant, property, room_type, stay):
        make_reservation(
            tenant,
            property,
            room_type,
            stay,
            guest_email="noTemplate@example.com",
            key_prefix="nt",
        )
        NotificationProjector.process_batch()
        job = NotificationJob.objects.get()
        assert job.template_id is None

        delivered = NotificationService.deliver(job_id=job.id, provider=FakeEmailProvider())
        assert delivered.status == JobStatus.FAILED
        assert "template" in delivered.last_error


@pytest.mark.django_db
class TestNotificationQuery:
    def test_pending_and_retryable(self, pending_job):
        assert list(NotificationQuery.pending_and_retryable()) == [pending_job]
        provider = FakeEmailProvider()
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert NotificationQuery.pending_and_retryable().count() == 0

    def test_by_guest(self, pending_job):
        results = NotificationQuery.by_guest(pending_job.recipient_guest)
        assert list(results) == [pending_job]

    def test_dead_lettered_for_tenant(self, tenant, pending_job, settings):
        settings.NOTIFICATION_MAX_RETRIES = 1
        provider = FakeEmailProvider()
        key = NotificationService._idempotency_key(pending_job.id)
        provider.fail_next(key)
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        NotificationService.deliver(job_id=pending_job.id, provider=provider)
        assert list(NotificationQuery.dead_lettered_for_tenant(tenant)) == [
            NotificationJob.objects.get(pk=pending_job.id)
        ]


def _force_delivering(job, *, stuck_seconds: float = 0):
    """Test-only simulation of TX1 having committed but the worker then
    crashing before TX2 ever runs — no provider call, no attempt recorded,
    exactly the failure window R0.4 recovers from. Backdates ``updated_at``
    via a queryset ``.update()`` (bypassing ``auto_now``) to simulate the
    job having sat in ``delivering`` for ``stuck_seconds``."""
    job = WorkflowRunner(job, field="status").run("start_delivering")
    if stuck_seconds:
        NotificationJob.objects.filter(pk=job.pk).update(
            updated_at=timezone.now() - timedelta(seconds=stuck_seconds)
        )
    return NotificationJob.objects.get(pk=job.pk)


@pytest.mark.django_db
class TestReapStuckDelivering:
    """R0.4 regression: a job whose worker crashed between TX1
    (pending/failed -> delivering) and TX2 (recording the attempt) must be
    recovered, not left stuck in ``delivering`` forever."""

    def test_stuck_job_past_timeout_is_reaped_to_failed(self, pending_job, settings):
        settings.NOTIFICATION_DELIVERING_TIMEOUT_SECONDS = 300
        job = _force_delivering(pending_job, stuck_seconds=301)

        reaped = NotificationService.reap_stuck_delivering()

        assert reaped == 1
        job.refresh_from_db()
        assert job.status == JobStatus.FAILED
        assert job.retry_count == 1
        assert "delivering" in job.last_error
        attempt = DeliveryAttempt.objects.get(notification_job=job)
        assert attempt.status == AttemptStatus.FAILED

    def test_job_within_timeout_is_left_alone(self, pending_job, settings):
        settings.NOTIFICATION_DELIVERING_TIMEOUT_SECONDS = 300
        job = _force_delivering(pending_job, stuck_seconds=10)  # well under the timeout

        reaped = NotificationService.reap_stuck_delivering()

        assert reaped == 0
        job.refresh_from_db()
        assert job.status == JobStatus.DELIVERING
        assert DeliveryAttempt.objects.filter(notification_job=job).count() == 0

    def test_reaping_is_safe_to_run_twice(self, pending_job, settings):
        settings.NOTIFICATION_DELIVERING_TIMEOUT_SECONDS = 300
        job = _force_delivering(pending_job, stuck_seconds=301)

        first = NotificationService.reap_stuck_delivering()
        second = NotificationService.reap_stuck_delivering()

        assert first == 1
        assert second == 0  # already FAILED, not delivering — nothing to reap
        job.refresh_from_db()
        assert job.retry_count == 1  # not double-incremented
        assert DeliveryAttempt.objects.filter(notification_job=job).count() == 1

    def test_reaped_job_becomes_retryable_and_can_still_succeed(self, pending_job, settings):
        settings.NOTIFICATION_DELIVERING_TIMEOUT_SECONDS = 300
        job = _force_delivering(pending_job, stuck_seconds=301)
        NotificationService.reap_stuck_delivering()

        # The reaped job is visible to the normal dispatch query again...
        assert list(NotificationQuery.pending_and_retryable()) == [
            NotificationJob.objects.get(pk=job.pk)
        ]
        # ...and a normal delivery attempt on it now succeeds cleanly.
        delivered = NotificationService.deliver(job_id=job.id, provider=FakeEmailProvider())
        assert delivered.status == JobStatus.DELIVERED
        assert delivered.retry_count == 1  # the reap's increment, not doubled by delivery

    def test_reaping_past_retry_ceiling_leads_to_dead_letter_on_next_attempt(
        self, pending_job, settings
    ):
        settings.NOTIFICATION_MAX_RETRIES = 1
        settings.NOTIFICATION_DELIVERING_TIMEOUT_SECONDS = 300
        job = _force_delivering(pending_job, stuck_seconds=301)
        NotificationService.reap_stuck_delivering()  # retry_count -> 1, at the ceiling

        job.refresh_from_db()
        assert job.retry_count == 1

        delivered = NotificationService.deliver(job_id=job.id, provider=FakeEmailProvider())
        assert delivered.status == JobStatus.DEAD_LETTERED
