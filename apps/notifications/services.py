"""NotificationService — delivery (M13, DDS S19, DMS S19).

The delivery transaction shape (M13 ruling — explicitly NOT one transaction
spanning the provider call):

    TX1: pending/failed -> delivering                      (commit)
    external provider call                                 (no open transaction)
    TX2: create DeliveryAttempt + delivered/failed/dead     (commit)

TX1 alone resolves the "two workers, same job" race: ``NotificationJob`` is
optimistically locked (``VersionedMixin``), so a concurrent second
``start_delivering()`` call finds the row already moved and raises
``ConcurrencyError`` before ever touching the provider or TX2.

The defensible guarantee: one logical ``NotificationJob`` per source
event/channel (the projector's job), one successful logical delivery state,
retry-safe worker processing, and observable (never silently dropped)
provider failures — NOT "exactly-once external delivery," which no fake
(or even most real) provider contracts actually support.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import AttemptStatus, DeliveryAttempt, JobStatus, NotificationJob
from apps.notifications.providers import EmailProvider, FakeEmailProvider, ProviderDeliveryError
from apps.shared.workflows.runner import WorkflowRunner

_default_provider = FakeEmailProvider()


class NotificationService:
    """Renders and delivers one ``NotificationJob`` at a time."""

    @staticmethod
    def _idempotency_key(job_id: int) -> str:
        return f"notification-job-{job_id}"

    @classmethod
    def deliver(cls, *, job_id: int, provider: EmailProvider | None = None) -> NotificationJob:
        provider = provider or _default_provider

        # TX1: pending/failed -> delivering. A job already at its retry
        # ceiling dead-letters here instead of attempting delivery again —
        # DB state (retry_count) is what decides retry-vs-dead-letter, not
        # a Celery-side counter.
        with transaction.atomic():
            job = NotificationJob.objects.select_related("template", "recipient_guest").get(
                pk=job_id
            )
            if (
                job.status == JobStatus.FAILED
                and job.retry_count >= settings.NOTIFICATION_MAX_RETRIES
            ):
                return WorkflowRunner(job, field="status").run(
                    "dead_letter", reason="retry ceiling reached"
                )
            job = WorkflowRunner(job, field="status").run("start_delivering")

        # External call — deliberately OUTSIDE any open transaction.
        job = NotificationJob.objects.select_related("template", "recipient_guest").get(pk=job_id)
        error = None
        provider_ref = ""
        if job.template is None:
            error = "no published template resolved for this job"
        elif job.recipient_guest is None or not job.recipient_guest.primary_email:
            error = "recipient has no email on file"
        else:
            try:
                subject = job.template.subject.format(**job.context)
                body = job.template.body.format(**job.context)
                provider_ref = provider.send(
                    to=job.recipient_guest.primary_email,
                    subject=subject,
                    body=body,
                    idempotency_key=cls._idempotency_key(job.id),
                )
            except (ProviderDeliveryError, KeyError) as exc:
                error = str(exc)

        # TX2: record the attempt + transition — no external call inside.
        with transaction.atomic():
            job = NotificationJob.objects.get(pk=job_id)
            if error is None:
                DeliveryAttempt.objects.create(
                    notification_job=job, status=AttemptStatus.SUCCEEDED, provider_ref=provider_ref
                )
                job = WorkflowRunner(job, field="status").run("mark_delivered")
            else:
                DeliveryAttempt.objects.create(
                    notification_job=job, status=AttemptStatus.FAILED, error=error
                )
                job.retry_count += 1
                job.last_error = error
                job = WorkflowRunner(job, field="status").run("mark_failed", reason=error)
        return job

    @classmethod
    def reap_stuck_delivering(cls, *, now=None) -> int:
        """R0.4: recover a job left in ``delivering`` because a worker
        crashed (or TX2 otherwise never ran) between the provider call
        succeeding/failing and the attempt being recorded — the gap
        ``deliver()``'s own docstring names as deliberately NOT one
        transaction. Without this, such a job is invisible to
        ``NotificationQuery.pending_and_retryable()`` (which only selects
        PENDING/FAILED) and would sit stuck forever.

        Each stuck job is re-locked and re-checked (still ``delivering``,
        still past the timeout) before being moved to ``failed`` — the SAME
        transition ``deliver()``'s own TX2 uses on a provider error, so the
        job re-enters the ordinary retry-or-dead-letter path with no new
        state machine. Idempotent and safe to run repeatedly or
        concurrently (mirrors ``ReservationService.expire()``'s sweep
        discipline): a job already moved on by the time this locks it is a
        no-op, not a double-reap.

        This does NOT protect against the provider having actually
        succeeded before the crash — that ambiguity is the same one
        ``deliver()`` already accepts (see its docstring: no "exactly-once
        external delivery" guarantee). ``provider.send()``'s idempotency
        key is the mitigation for a real provider that honors one; the
        in-repo ``FakeEmailProvider`` does.
        """
        cutoff = (now or timezone.now()) - timedelta(
            seconds=settings.NOTIFICATION_DELIVERING_TIMEOUT_SECONDS
        )
        stuck_ids = list(
            NotificationJob.objects.filter(
                status=JobStatus.DELIVERING, updated_at__lt=cutoff
            ).values_list("id", flat=True)
        )
        reaped = 0
        for job_id in stuck_ids:
            with transaction.atomic():
                job = NotificationJob.objects.select_for_update().get(pk=job_id)
                if job.status != JobStatus.DELIVERING or job.updated_at >= cutoff:
                    continue  # already resolved (or re-stamped) since the scan above
                DeliveryAttempt.objects.create(
                    notification_job=job,
                    status=AttemptStatus.FAILED,
                    error=(
                        f"stuck in delivering for over "
                        f"{settings.NOTIFICATION_DELIVERING_TIMEOUT_SECONDS}s — reaped"
                    ),
                )
                job.retry_count += 1
                job.last_error = "reaped: stuck in delivering (worker likely crashed mid-delivery)"
                WorkflowRunner(job, field="status").run(
                    "mark_failed", reason="reaped after delivering timeout"
                )
                reaped += 1
        return reaped


class NotificationQuery:
    """Read-only selectors over ``notification_job``."""

    @staticmethod
    def pending_and_retryable():
        return NotificationJob.objects.filter(status__in=[JobStatus.PENDING, JobStatus.FAILED])

    @staticmethod
    def by_guest(guest_profile):
        return NotificationJob.objects.filter(recipient_guest=guest_profile).order_by("-created_at")

    @staticmethod
    def dead_lettered_for_tenant(tenant):
        return NotificationJob.objects.filter(tenant=tenant, status=JobStatus.DEAD_LETTERED)
