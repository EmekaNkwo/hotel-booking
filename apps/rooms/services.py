"""Room services (M3).

RoomStateMachine: single entry point for all room state transitions.
Uses WorkflowRunner for django-fsm integration with audit/outbox.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.properties.models import Building, Floor, Property
from apps.rooms.models import Room, RoomStateEvent, RoomType
from apps.shared.tenancy import require_current_tenant
from apps.shared.workflows.runner import WorkflowRunner


class RoomStateMachine:
    """Single entry point for Room operational-state transitions (M3)."""

    @staticmethod
    def apply(room, transition_name: str, actor=None, reason: str = ""):
        """Execute a validated state transition atomically.

        Orchestrates:
        - django-fsm transition (with guards, RBAC via WorkflowRunner)
        - persistence of the new Room state
        - immutable RoomStateEvent (append-only audit trail)
        - generic AuditService record
        - room.state_changed outbox event

        All writes are atomic.
        """
        # WorkflowRunner.run() handles the full atomic transaction internally:
        # guards/permissions → state change → save → outbox → audit.
        # We must add the RoomStateEvent row in the SAME transaction, so we
        # wrap the runner in a parent transaction and insert the event after
        # the state change is committed by the runner.
        with transaction.atomic():
            before_state = room.operational_state
            updated = WorkflowRunner(room, field="operational_state").run(
                transition_name,
                actor=actor,
                reason=reason,
            )
            after_state = updated.operational_state

            # Only record an event if the state actually changed.
            if before_state != after_state:
                RoomStateEvent.objects.create(
                    tenant=room.tenant,
                    room=updated,
                    from_state=before_state,
                    to_state=after_state,
                    transition=transition_name,
                    actor_id=getattr(actor, "id", 0) or 0,
                    actor_type=type(actor).__name__ if actor else "system",
                    reason=reason or "",
                )

        return updated


class RoomService:
    """Room CRUD and business operations."""

    def create_room(
        self,
        property_id: int,
        room_type_id: int,
        building_id: int = None,
        floor_id: int = None,
        code: str = None,
    ):
        """Create a new room with validation and tenant isolation."""
        tenant = require_current_tenant()

        with transaction.atomic():
            # Validate Property exists and belongs to tenant
            try:
                property_obj = Property.objects.get(id=property_id, tenant=tenant)
            except Property.DoesNotExist:
                raise ValidationError(f"Property {property_id} not found or access denied")

            # Validate RoomType exists, is active, and belongs to tenant
            try:
                room_type_obj = RoomType.objects.get(
                    id=room_type_id,
                    tenant=tenant,
                    status=RoomType.Status.ACTIVE
                )
            except RoomType.DoesNotExist:
                raise ValidationError(f"RoomType {room_type_id} not found, inactive, or access denied")

            # Validate Building if provided
            building_obj = None
            if building_id is not None:
                try:
                    building_obj = Building.objects.get(id=building_id, tenant=tenant)
                except Building.DoesNotExist:
                    raise ValidationError(f"Building {building_id} not found or access denied")

            # Validate Floor if provided
            floor_obj = None
            if floor_id is not None:
                try:
                    floor_obj = Floor.objects.get(id=floor_id, tenant=tenant)
                except Floor.DoesNotExist:
                    raise ValidationError(f"Floor {floor_id} not found or access denied")

            # Create the Room
            room = Room.objects.create(
                tenant=tenant,
                property=property_obj,
                room_type=room_type_obj,
                building=building_obj,
                floor=floor_obj,
                code=code,
                operational_state=Room.OperationalState.VACANT_CLEAN,
            )

            # The Room.save() method will enforce state machine usage
            # No need to call RoomStateMachine.apply() for initial creation
            # as the default state is VACANT_CLEAN and no transition is needed

            return room

    def update_room(self, room_id: int, **kwargs):
        """Update room fields with validation and optimistic locking."""
        # Get the room with tenant isolation
        try:
            room = Room.objects.get(id=room_id, tenant=require_current_tenant())
        except Room.DoesNotExist:
            raise ValidationError(f"Room {room_id} not found or access denied")

        # Prevent direct operational state changes
        if 'operational_state' in kwargs:
            raise ValidationError(
                "Direct operational state changes are prohibited. "
                "Use RoomStateMachine.apply() for state transitions."
            )

        # Define which fields can be updated via this service
        updatable_fields = {'code', 'building_id', 'floor_id'}

        # Validate that only allowed fields are being updated
        invalid_fields = set(kwargs.keys()) - updatable_fields
        if invalid_fields:
            raise ValidationError(f"Cannot update fields: {', '.join(invalid_fields)}")

        with transaction.atomic():
            # Store original state for optimistic locking/check
            original_state = room.operational_state

            # Handle building_id and floor_id conversions
            if 'building_id' in kwargs:
                building_id = kwargs.pop('building_id')
                if building_id is not None:
                    try:
                        room.building = Building.objects.get(id=building_id, tenant=require_current_tenant())
                    except Building.DoesNotExist:
                        raise ValidationError(f"Building {building_id} not found or access denied")
                else:
                    room.building = None

            if 'floor_id' in kwargs:
                floor_id = kwargs.pop('floor_id')
                if floor_id is not None:
                    try:
                        room.floor = Floor.objects.get(id=floor_id, tenant=require_current_tenant())
                    except Floor.DoesNotExist:
                        raise ValidationError(f"Floor {floor_id} not found or access denied")
                else:
                    room.floor = None

            # Update remaining fields (code)
            for field, value in kwargs.items():
                setattr(room, field, value)

            # Save with optimistic locking (handled by Room.save())
            room.save()

            return room, original_state

    def retire_room_type(self, room_type_id: int):
        """Retire a room type (soft delete) respecting existing rooms."""
        tenant = require_current_tenant()

        try:
            room_type_obj = RoomType.objects.get(id=room_type_id, tenant=tenant)
        except RoomType.DoesNotExist:
            raise ValidationError(f"RoomType {room_type_id} not found or access denied")

        if room_type_obj.status == RoomType.Status.RETIRED:
            # Already retired, nothing to do
            return room_type_obj

        # Check if there are any rooms using this type (should be allowed per spec)
        # The spec says to respect existing rooms referencing the type,
        # which means we don't prevent retirement if rooms exist

        with transaction.atomic():
            room_type_obj = RoomType.objects.get(id=room_type_id)
            # Immutable pattern: create a new instance with the retired status
            # rather than mutating the existing object in place
            retired_room_type = RoomType(
                pk=room_type_obj.pk,
                tenant=room_type_obj.tenant,
                code=room_type_obj.code,
                name=room_type_obj.name,
                max_occupancy=room_type_obj.max_occupancy,
                attributes=room_type_obj.attributes,
                status=RoomType.Status.RETIRED,
            )
            retired_room_type.save(update_fields=["status"])
            return retired_room_type

    def get_room_state_history(self, room_id: int):
        """Get tenant-scoped room state history in chronological order."""
        try:
            # Verify room exists and tenant has access
            room = Room.objects.get(id=room_id, tenant=require_current_tenant())
        except Room.DoesNotExist:
            raise ValidationError(f"Room {room_id} not found or access denied")

        # Return RoomStateEvent history ordered chronologically
        return RoomStateEvent.objects.filter(
            room=room,
            tenant=require_current_tenant()
        ).order_by('created_at')