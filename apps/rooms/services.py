"""Room services (M3).

RoomStateMachine: single entry point for all room state transitions.
Uses WorkflowRunner for django-fsm integration with audit/outbox.
"""

from apps.rooms.models import Room, RoomType
from apps.shared.workflows.runner import WorkflowRunner


class RoomStateMachine:
    """Room operational state machine.

    Single entry point: apply(room, transition, actor, reason).
    Uses WorkflowRunner for atomic state change + audit + outbox.
    """

    @staticmethod
    def apply(room, transition_name, actor, reason=""):
        """Apply a state transition to a room.

        Args:
            room: Room instance
            transition_name: Name of transition (e.g., "allocate", "checkout")
            actor: User or system actor
            reason: Human-readable reason for transition

        Returns:
            Updated Room instance

        Raises:
            TransitionNotAllowed: If transition is undefined or forbidden
        """
        runner = WorkflowRunner(room)
        return runner.run(transition_name, actor=actor, reason=reason)


class RoomService:
    """Room CRUD and business operations."""

    @staticmethod
    def create_room(tenant, property, room_type, code, building=None, floor=None):
        """Create a new room."""
        return Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code=code,
            building=building,
            floor=floor,
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

    @staticmethod
    def update_room(room, **kwargs):
        """Update room attributes."""
        for field, value in kwargs.items():
            setattr(room, field, value)
        room.save()
        return room

    @staticmethod
    def retire_room_type(room_type):
        """Retire a room type (soft delete)."""
        room_type.status = RoomType.Status.RETIRED
        room_type.save(update_fields=["status"])
        return room_type