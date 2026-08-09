"""Eventing & outbox — the transactional event spine (M1.3, DR-08).

``DomainEvent`` is the durable, append-only event log — the outbox's long-term
store and the source projections rebuild from (DDS §22). ``OutboxEvent`` is the
transactional outbox: written in the SAME database transaction as the state
change that caused it, promoted to a ``DomainEvent`` by the relay, then
dead-lettered on failure with attempts/last_error.

Event payloads hold ONLY primitives (dicts of str/int/bool/None/lists) — never
value objects. Value objects are serialized at the service boundary; the event
is schema-versioned by ``event_version`` (R19) so consumers can decode old
shapes safely.
"""

import uuid

from django.db import models
from django.utils import timezone

from apps.shared.models.mixins import AppendOnlyMixin, TenantScopedMixin, TimeStampedMixin
from apps.shared.models.recipes import partial_index, status_constraint


class DomainEventStatus(models.TextChoices):
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class DomainEvent(AppendOnlyMixin, TenantScopedMixin):
    """Durable, append-only event log (DDS §22 ``domain_event``).

    One row per published domain event. Immutable once written; partitioned by
    ``occurred_at`` and RLS-scoped in later milestones (M7/M2). The natural key
    ``(tenant_id, event_id_uuid)`` makes replay idempotent — a relay can never
    duplicate an event.
    """

    event_id_uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=200)  # dotted name, e.g. "booking.confirmed"
    event_version = models.PositiveSmallIntegerField(default=1)  # R19 schema versioning
    aggregate_type = models.CharField(max_length=100)  # e.g. "booking"
    aggregate_id = models.CharField(max_length=100)  # string form of the aggregate pk
    occurred_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(
        max_length=20, choices=DomainEventStatus.choices, default=DomainEventStatus.PUBLISHED
    )
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "shared"
        db_table = "domain_event"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "event_id_uuid"], name="domain_event_uq_tenant_uuid"
            ),
            status_constraint("status", DomainEventStatus, "domain_event_status_valid"),
        ]
        indexes = [
            models.Index(
                fields=["tenant_id", "-occurred_at"], name="domain_event_tenant_occurred"
            ),
            models.Index(
                fields=["aggregate_type", "aggregate_id", "-occurred_at"],
                name="domain_event_ix_aggregate",
            ),
            models.Index(
                fields=["event_type", "-occurred_at"], name="domain_event_ix_type_occurred"
            ),
        ]


class OutboxEventStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PUBLISHED = "published", "Published"
    DEAD_LETTERED = "dead_lettered", "Dead-lettered"


class OutboxEvent(TimeStampedMixin, TenantScopedMixin):
    """Transactional outbox row (DDS §22 ``outbox_event``, DR-08).

    Created in the same DB transaction as the state change that caused it. The
    relay scans ``status='pending'`` (partial index), appends the matching
    ``DomainEvent`` and marks this row ``published`` in one transaction, and
    bumps ``attempts``/``last_error`` toward ``dead_lettered`` on failure.
    Purged after delivery + grace; partitioned by ``created_at`` in M7.
    """

    event_type = models.CharField(max_length=200)
    event_version = models.PositiveSmallIntegerField(default=1)
    aggregate_type = models.CharField(max_length=100)
    aggregate_id = models.CharField(max_length=100)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=OutboxEventStatus.choices, default=OutboxEventStatus.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        app_label = "shared"
        db_table = "outbox_event"
        constraints = [
            status_constraint("status", OutboxEventStatus, "outbox_event_status_valid"),
        ]
        indexes = [
            partial_index(
                ["created_at"],
                models.Q(status=OutboxEventStatus.PENDING),
                "outbox_event_pending_created",
            ),
            partial_index(
                ["updated_at"],
                models.Q(status=OutboxEventStatus.DEAD_LETTERED),
                "outbox_event_deadl_updated",
            ),
        ]
