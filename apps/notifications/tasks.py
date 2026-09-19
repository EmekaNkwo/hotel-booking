"""Notification Celery tasks (M13).

Real Celery retry/backoff via ``self.retry()`` (Celery's native mechanism —
no custom scheduler, no Redis-based retry queue). The DB
(``NotificationJob.status``/``retry_count``) stays authoritative:
``NotificationService.deliver()`` decides retry-vs-dead-letter from
persisted state, not from Celery's own retry counter — the task's
``max_retries`` is set slightly ABOVE ``settings.NOTIFICATION_MAX_RETRIES``
purely as a safety ceiling (so Celery can never give up before the DB does;
in practice the DB always dead-letters first, at which point ``deliver()``
stops returning a ``failed`` status and the task stops retrying on its own).
"""

from django.conf import settings

from apps.notifications.models import JobStatus
from apps.notifications.projectors import NotificationProjector
from apps.notifications.services import NotificationQuery, NotificationService
from apps.shared.exceptions import ConcurrencyError
from celery import shared_task


class NotificationNotYetDelivered(Exception):
    """The job failed this attempt but has not yet hit its retry ceiling
    (still ``failed``, not ``dead_lettered``) — triggers a Celery retry."""


@shared_task(bind=True, name="notifications.deliver_job")
def deliver_notification_job(self, job_id: int) -> str:
    try:
        job = NotificationService.deliver(job_id=job_id)
    except ConcurrencyError:
        # Another worker already claimed this job — a harmless lost race,
        # not a failure worth retrying.
        return "lost_race"

    if job.status == JobStatus.FAILED:
        backoff_seconds = min(2**self.request.retries, 600)  # simple exponential, capped
        raise self.retry(
            exc=NotificationNotYetDelivered(job.last_error),
            countdown=backoff_seconds,
            max_retries=settings.NOTIFICATION_MAX_RETRIES + 1,
        )
    return job.status


@shared_task(name="notifications.dispatch_notifications")
def dispatch_notifications() -> int:
    """Fold new events into jobs, then enqueue delivery for every
    pending/retryable job. Safe to run repeatedly/concurrently — the
    projector's checkpoint and the UniqueConstraint make re-processing a
    no-op; ``deliver_notification_job`` is itself idempotent per job."""
    NotificationProjector.process_batch()
    job_ids = list(NotificationQuery.pending_and_retryable().values_list("id", flat=True))
    for job_id in job_ids:
        deliver_notification_job.delay(job_id)
    return len(job_ids)


@shared_task(name="notifications.reap_stuck_delivering")
def reap_stuck_delivering() -> int:
    """R0.4: periodic reconciler for jobs left in ``delivering`` past
    ``NOTIFICATION_DELIVERING_TIMEOUT_SECONDS`` (a worker crashed between
    TX1 and TX2 — see ``NotificationService.deliver()``'s docstring for the
    transaction shape). Moves each back to ``failed`` so the NEXT
    ``dispatch_notifications`` tick picks it up again through the ordinary
    retry-or-dead-letter path — this task does not deliver anything
    itself."""
    return NotificationService.reap_stuck_delivering()
