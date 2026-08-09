"""Transactional outbox — producer and relay (M1.3, DR-08).

The producer writes an ``OutboxEvent`` row; the caller is responsible for it
being in the SAME database transaction as the state change that caused it
(call ``record_event`` inside your ``transaction.atomic()``). The relay then
promotes pending rows into the append-only ``DomainEvent`` log and marks them
published — atomically, idempotently, and with dead-lettering.

The relay is a batch callable (Celery/scheduler wiring comes in M2+); each row
is promoted inside its own transaction so one bad payload cannot block the
batch. The stable ``event_id_uuid`` derived from the outbox row pk makes
concurrent relays converge on ONE ``DomainEvent`` (unique constraint), so
promotion is safe under duplicate delivery.
"""

import uuid

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.shared.models import (
    DomainEvent,
    DomainEventStatus,
    OutboxEvent,
    OutboxEventStatus,
)
from apps.shared.models.recipes import conditional_update

_OUTBOX_UUID_NS = uuid.uuid5(uuid.NAMESPACE_URL, "hotel-booking/outbox")


class OutboxService:
    """The producer side: write an outbox row alongside the state change.

    ``record_event`` is a plain insert — it must be called INSIDE the caller's
    transaction so the event and the change that caused it commit (or roll back)
    together (DR-08). It intentionally performs no side effects itself.
    """

    @staticmethod
    def record_event(
        *,
        event_type: str,
        tenant_id: int,
        payload: dict | None = None,
        aggregate_type: str = "",
        aggregate_id: str = "",
        event_version: int = 1,
    ) -> OutboxEvent:
        return OutboxEvent.objects.create(
            event_type=event_type,
            event_version=event_version,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload or {},
            tenant_id=tenant_id,
        )


class OutboxRelay:
    """Promotes pending outbox rows into the durable ``DomainEvent`` log.

    ``publish_batch`` processes up to ``batch_size`` rows, oldest first (the
    partial index on pending rows makes this a tiny hot scan). Each promotion
    is atomic; a failure increments ``attempts`` and dead-letters the row after
    ``max_attempts`` so a poisoned payload cannot block the queue forever.
    """

    def __init__(self, max_attempts: int = 5):
        self.max_attempts = max_attempts

    def publish_batch(self, batch_size: int = 100) -> int:
        pending = (
            OutboxEvent.objects.filter(status=OutboxEventStatus.PENDING)
            .order_by("created_at", "id")[:batch_size]
        )
        published = 0
        for row in pending:
            if self._publish(row):
                published += 1
        return published

    def _publish(self, row: OutboxEvent) -> bool:
        try:
            self._promote(row)
            return True
        except Exception as exc:  # noqa: BLE001 — the relay must never die on one row
            self._dead_letter(row, exc)
            return False

    def _promote(self, row: OutboxEvent) -> None:
        event_id = self._stable_event_id(row)
        with transaction.atomic():
            # Ensure the DomainEvent exists exactly once — the (tenant, uuid)
            # unique constraint makes concurrent relays converge on one row.
            DomainEvent.objects.get_or_create(
                event_id_uuid=event_id,
                tenant_id=row.tenant_id,
                defaults={
                    "event_type": row.event_type,
                    "event_version": row.event_version,
                    "aggregate_type": row.aggregate_type,
                    "aggregate_id": row.aggregate_id,
                    "occurred_at": row.created_at,
                    "status": DomainEventStatus.PUBLISHED,
                    "payload": row.payload,
                },
            )
            # Mark the outbox row published; a concurrent relay's identical
            # update just affects 0 rows, which is fine (idempotent).
            conditional_update(
                OutboxEvent.objects.filter(pk=row.pk),
                {"status": OutboxEventStatus.PENDING},
                {
                    "status": OutboxEventStatus.PUBLISHED,
                    "updated_at": timezone.now(),
                },
            )

    def _dead_letter(self, row: OutboxEvent, exc: Exception) -> None:
        with transaction.atomic():
            conditional_update(
                OutboxEvent.objects.filter(pk=row.pk),
                {},
                {
                    "attempts": F("attempts") + 1,
                    "last_error": str(exc)[:500],
                    "updated_at": timezone.now(),
                },
            )
            if row.attempts + 1 >= self.max_attempts:
                # Only dead-letter if it is still pending — a concurrent relay
                # may have published it while we were failing.
                conditional_update(
                    OutboxEvent.objects.filter(
                        pk=row.pk, status=OutboxEventStatus.PENDING
                    ),
                    {},
                    {"status": OutboxEventStatus.DEAD_LETTERED, "updated_at": timezone.now()},
                )

    @staticmethod
    def _stable_event_id(row: OutboxEvent) -> uuid.UUID:
        """Deterministic event uuid per outbox row, so retries and concurrent
        relays never duplicate a domain event."""
        return uuid.uuid5(_OUTBOX_UUID_NS, f"outbox:{row.pk}")
