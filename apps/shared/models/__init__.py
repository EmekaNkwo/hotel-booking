"""Shared models — the Django shape of the Shared Kernel.

Organized as a package so each concern has a home:

- ``recipes`` — packaged persistence idioms (partial_index, conditional_update,
  status_constraint).
- ``mixins`` — abstract bases (TimeStamped, TenantScoped, Versioned,
  AppendOnly, Entity).
- ``events`` — DomainEvent (append-only log) + OutboxEvent (transactional outbox).
- ``idempotency`` — IdempotencyRecord (dedup spine).
- ``audit`` — AuditLog (append-only, typed refs).
- ``projection`` — ProjectionState (idempotent projection checkpoints).
"""

from apps.shared.models.audit import AuditLog
from apps.shared.models.events import DomainEvent, DomainEventStatus, OutboxEvent, OutboxEventStatus
from apps.shared.models.idempotency import IdempotencyRecord, IdempotencyStatus
from apps.shared.models.mixins import (
    AppendOnlyMixin,
    AppendOnlyQuerySet,
    EntityMixin,
    TenantScopedMixin,
    TimeStampedMixin,
    VersionedMixin,
)
from apps.shared.models.projection import ProjectionState, ProjectionStatus
from apps.shared.models.recipes import conditional_update, partial_index, status_constraint

__all__ = [
    "AppendOnlyMixin",
    "AppendOnlyQuerySet",
    "AuditLog",
    "conditional_update",
    "DomainEvent",
    "DomainEventStatus",
    "EntityMixin",
    "IdempotencyRecord",
    "IdempotencyStatus",
    "OutboxEvent",
    "OutboxEventStatus",
    "partial_index",
    "ProjectionState",
    "ProjectionStatus",
    "status_constraint",
    "TenantScopedMixin",
    "TimeStampedMixin",
    "VersionedMixin",
]
