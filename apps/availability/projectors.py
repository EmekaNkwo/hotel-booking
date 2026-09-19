"""RoomStateProjector — the ``room.state_changed`` consumer (M7 scope item 11).

Consumes the REAL producer that already exists: ``apps/rooms/models.py``
emits ``room.state_changed`` (payload ``{"from": ..., "to": ...}``) through
the outbox/``WorkflowRunner`` on every operational-state transition (M3).
There is no ``room.type_retired`` producer anywhere in the codebase yet
(``RoomService.retire_room_type`` does not emit one) — per M7 scope, this
projector does NOT invent one; only the real event is consumed.

An OOO/OOS room is unsellable; every other operational state (including the
mid-cycle ``cleaning``/``inspected`` states) is sellable inventory that just
happens to need housekeeping before the next guest — DDS S6+7 models this as
a single boolean via ``availability_slot.out_of_service``, not a full
room-readiness state machine. So the projector only reacts to a transition
that CROSSES the OOO/OOS boundary; transitions on either side of it (e.g.
``vacant_dirty -> cleaning``) are a no-op here.

Idempotency: ``ProjectionState`` (M1.6) checkpoints ``(occurred_at, id)`` of
the last folded event — the row is only shipped once per query (strictly
GREATER than the checkpoint), so replaying ``process_batch()`` after a crash
or a manual re-run never re-applies an already-processed event.
"""

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.availability.services import InventoryService
from apps.rooms.models import Room
from apps.shared.models import DomainEvent, ProjectionState, ProjectionStatus

EVENT_TYPE = "room.state_changed"
PROJECTION_NAME = "availability.room_state"

_UNSELLABLE_STATES = {
    Room.OperationalState.OUT_OF_SERVICE,
    Room.OperationalState.OUT_OF_ORDER,
}


class RoomStateProjector:
    """Folds ``room.state_changed`` events into ``availability_slot.out_of_service``."""

    @classmethod
    def process_batch(cls, *, horizon_days: int, batch_size: int = 100) -> int:
        """Process up to ``batch_size`` pending events; return how many were applied.

        Stops (without advancing past) the first event whose application
        raises — e.g. the invariant CHECK rejects the adjustment — so the
        projection surfaces as ``FAILED``/``last_error`` (M1.6) rather than
        silently skipping or losing an event.
        """
        state, _ = ProjectionState.objects.get_or_create(
            projection_name=PROJECTION_NAME, defaults={"status": ProjectionStatus.ACTIVE}
        )
        processed = 0
        for event in cls._pending_events(state, batch_size):
            try:
                with transaction.atomic():
                    cls._apply(event, horizon_days=horizon_days)
                    state.last_event_id = cls._checkpoint(event)
                    state.last_processed_at = timezone.now()
                    state.status = ProjectionStatus.ACTIVE
                    state.last_error = ""
                    state.save(
                        update_fields=[
                            "last_event_id",
                            "last_processed_at",
                            "status",
                            "last_error",
                            "updated_at",
                        ]
                    )
            except Exception as exc:  # noqa: BLE001 — surface, never silently drop an event
                state.status = ProjectionStatus.FAILED
                state.last_error = str(exc)[:500]
                state.save(update_fields=["status", "last_error", "updated_at"])
                break
            processed += 1
        return processed

    @staticmethod
    def _checkpoint(event: DomainEvent) -> str:
        return f"{event.occurred_at.isoformat()}|{event.pk}"

    @staticmethod
    def _pending_events(state: ProjectionState, batch_size: int):
        qs = DomainEvent.objects.filter(event_type=EVENT_TYPE).order_by("occurred_at", "id")
        if state.last_event_id:
            occurred_at_str, _, pk_str = state.last_event_id.partition("|")
            occurred_at = datetime.fromisoformat(occurred_at_str)
            checkpoint_pk = int(pk_str)
            qs = qs.filter(
                Q(occurred_at__gt=occurred_at)
                | (Q(occurred_at=occurred_at) & Q(id__gt=checkpoint_pk))
            )
        return list(qs[:batch_size])

    @classmethod
    def _apply(cls, event: DomainEvent, *, horizon_days: int) -> None:
        from_state = (event.payload or {}).get("from")
        to_state = (event.payload or {}).get("to")
        was_unsellable = from_state in _UNSELLABLE_STATES
        is_unsellable = to_state in _UNSELLABLE_STATES
        if was_unsellable == is_unsellable:
            return  # did not cross the OOO/OOS boundary — nothing to project

        room = Room.objects.unscoped().filter(pk=event.aggregate_id).first()
        if room is None:
            return  # room no longer resolvable; nothing to project

        today = timezone.now().date()
        InventoryService.adjust_out_of_service(
            tenant_id=event.tenant_id,
            property_id=room.property_id,
            room_type_id=room.room_type_id,
            start_date=today,
            end_date=today + timedelta(days=horizon_days),
            delta=1 if is_unsellable else -1,
        )
