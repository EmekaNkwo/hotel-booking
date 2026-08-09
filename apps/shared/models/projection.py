"""Projection state — the checkpoint for idempotent projection consumers (M1.6).

Search/timeline/reporting ETL consume the ``domain_event`` log and write
projections. ``ProjectionState`` records, per projection, the last event
processed, so a consumer can resume exactly-once after a crash. One row per
projection name (the primary key) — platform-level, deliberately NOT
tenant-scoped: projections aggregate across tenants.
"""

from django.db import models

from apps.shared.models.mixins import TimeStampedMixin
from apps.shared.models.recipes import status_constraint


class ProjectionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    FAILED = "failed", "Failed"
    STALLED = "stalled", "Stalled"


class ProjectionState(TimeStampedMixin):
    """Checkpoint row for one projection consumer (DDS §22 ``projection_state``).

    ``last_event_id`` is the ``(occurred_at, id)`` of the last domain event
    folded into the projection; ``status``/``last_error`` surface a consumer
    that needs attention so ETL can resume, not silently skip.
    """

    projection_name = models.CharField(max_length=100, primary_key=True)
    last_event_id = models.CharField(max_length=100, blank=True, default="")
    last_processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=ProjectionStatus.choices, default=ProjectionStatus.ACTIVE
    )
    last_error = models.TextField(blank=True, default="")

    class Meta:
        app_label = "shared"
        db_table = "projection_state"
        constraints = [
            status_constraint("status", ProjectionStatus, "projection_state_status_valid"),
        ]
