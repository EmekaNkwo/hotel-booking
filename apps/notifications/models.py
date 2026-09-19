"""Notification models (M13, DDS S19, DMS S19).

``NotificationJob`` is the reliability boundary (DDS S19: "LOCK optimistic")
— a ``WorkflowRunner`` FSM, mirroring ``HousekeepingTask`` (M12): no
``select_for_update()`` anywhere here. ``DeliveryAttempt`` is the immutable
per-try log. ``NotificationTemplate``/``ChannelPreference`` are the
tenant-configurable content/delivery-rule tables DDS names.

Scope (M13 ruling): one channel (``email``, a plain string column, not a
closed enum — adding a second channel later is a data change, not a
migration). No quiet hours on ``ChannelPreference``. ``context`` on
``NotificationJob`` is a necessary addition beyond DDS's abbreviated
schema — the immutable, pinned rendering payload captured at job-creation
time so delivery never re-queries the live aggregate (mirrors the
price/policy snapshot philosophy from M8/M9).
"""

from django.db import models
from django_fsm import FSMField

from apps.shared.models.mixins import EntityMixin, TimeStampedMixin
from apps.shared.models.recipes import partial_index, status_constraint
from apps.shared.workflows.runner import workflow_transition

DEFAULT_LOCALE = "en"


class TemplateStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"


class NotificationTemplate(EntityMixin):
    """Tenant-configurable, per-channel, per-locale content (DDS S19)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="notification_templates"
    )
    notification_type = models.CharField(max_length=64)
    channel = models.CharField(max_length=16)
    locale = models.CharField(max_length=16, default=DEFAULT_LOCALE)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(
        max_length=16, choices=TemplateStatus.choices, default=TemplateStatus.DRAFT
    )

    objects = models.Manager()

    class Meta:
        app_label = "notifications"
        db_table = "notification_template"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "notification_type", "channel", "locale"],
                name="notif_template_uq_type_channel_locale",
            ),
            status_constraint("status", TemplateStatus, "notif_template_valid_status"),
        ]

    def __str__(self) -> str:
        return f"{self.notification_type}/{self.channel}/{self.locale} ({self.status})"


class ChannelPreference(EntityMixin):
    """A guest's per-channel suppression flag (DDS S19). No quiet hours
    (M13 ruling) — nothing in the delivery path is time-window-sensitive."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="channel_preferences"
    )
    guest_profile = models.ForeignKey(
        "guests.GuestProfile", on_delete=models.RESTRICT, related_name="channel_preferences"
    )
    channel = models.CharField(max_length=16)
    suppressed = models.BooleanField(default=False)

    objects = models.Manager()

    class Meta:
        app_label = "notifications"
        db_table = "channel_preference"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "guest_profile", "channel"],
                name="chan_pref_uq_tenant_guest_channel",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.guest_profile_id}:{self.channel} suppressed={self.suppressed}"


class JobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DELIVERING = "delivering", "Delivering"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    DEAD_LETTERED = "dead_lettered", "Dead-lettered"


class NotificationJob(EntityMixin):
    """One notification to one guest, triggered by one event (DDS S19
    ``notification_job``, the reliability/outbox-consumer boundary)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="notification_jobs"
    )
    source_event = models.ForeignKey(
        "shared.DomainEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_jobs",
    )
    recipient_guest = models.ForeignKey(
        "guests.GuestProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_jobs",
    )
    notification_type = models.CharField(max_length=64)
    channel = models.CharField(max_length=16)
    template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
    )
    # Immutable rendering context, pinned at job-creation time (M13 ruling —
    # never re-queried from the live aggregate at delivery time).
    context = models.JSONField(default=dict, blank=True)
    status = FSMField(max_length=16, choices=JobStatus.choices, default=JobStatus.PENDING)
    retry_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    objects = models.Manager()

    class Meta:
        app_label = "notifications"
        db_table = "notification_job"
        constraints = [
            models.UniqueConstraint(
                fields=["source_event", "channel"], name="notif_job_uq_source_event_channel"
            ),
            status_constraint("status", JobStatus, "notif_job_valid_status"),
        ]
        indexes = [
            partial_index(
                ["status", "created_at"],
                models.Q(status__in=[JobStatus.PENDING, JobStatus.DELIVERING]),
                "notif_job_ix_relay_queue",
            ),
            partial_index(
                ["status", "updated_at"],
                models.Q(status=JobStatus.DEAD_LETTERED),
                "notif_job_ix_dead_lettered",
            ),
            models.Index(fields=["tenant", "created_at"], name="notif_job_ix_tenant_created"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.notification_type}/{self.channel} "
            f"-> guest={self.recipient_guest_id} ({self.status})"
        )

    # ------------------------------------------------------------------
    # State machine (M13 ruling):
    #   pending/failed -> delivering -> delivered
    #   delivering -> failed -> {delivering (retry), dead_lettered (ceiling)}
    # A delivered job has no outgoing transition.
    # ------------------------------------------------------------------

    @workflow_transition(
        field="status",
        source=[JobStatus.PENDING, JobStatus.FAILED],
        target=JobStatus.DELIVERING,
        event=None,
    )
    def start_delivering(self):
        """Begin (or retry) a delivery attempt."""

    @workflow_transition(
        field="status",
        source=JobStatus.DELIVERING,
        target=JobStatus.DELIVERED,
        event="notification.delivered",
    )
    def mark_delivered(self):
        """Provider accepted the send — terminal, successful state."""

    @workflow_transition(
        field="status", source=JobStatus.DELIVERING, target=JobStatus.FAILED, event=None
    )
    def mark_failed(self):
        """Provider call failed — retryable (not yet dead-lettered)."""

    @workflow_transition(
        field="status",
        source=JobStatus.FAILED,
        target=JobStatus.DEAD_LETTERED,
        event="notification.failed",
    )
    def dead_letter(self):
        """Retry ceiling reached — terminal, observable failure (DMS: no silent loss)."""


class AttemptStatus(models.TextChoices):
    ATTEMPTED = "attempted", "Attempted"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


class DeliveryAttempt(TimeStampedMixin):
    """One provider interaction (DDS S19). Immutable — one row per try."""

    notification_job = models.ForeignKey(
        NotificationJob, on_delete=models.CASCADE, related_name="delivery_attempts"
    )
    status = models.CharField(max_length=16, choices=AttemptStatus.choices)
    provider_ref = models.CharField(max_length=200, blank=True, default="")
    error = models.TextField(blank=True, default="")

    objects = models.Manager()

    class Meta:
        app_label = "notifications"
        db_table = "delivery_attempt"
        constraints = [
            status_constraint("status", AttemptStatus, "delivery_attempt_valid_status"),
        ]
        indexes = [
            models.Index(fields=["notification_job"], name="delivery_attempt_ix_job"),
            models.Index(fields=["provider_ref"], name="delivery_attempt_ix_ref"),
        ]

    def __str__(self) -> str:
        return f"job={self.notification_job_id} {self.status}"
