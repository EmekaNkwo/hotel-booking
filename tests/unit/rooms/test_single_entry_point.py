"""Test that RoomStateMachine is the only entry point for state transitions."""

import pytest

from apps.rooms.models import Room, RoomStateEvent
from apps.rooms.services import RoomStateMachine


class TestSingleEntryPoint:
    @pytest.mark.django_db
    def test_direct_django_fsm_call_bypasses_audit(self, tenant, property, room_type):
        """Calling the django-fsm transition method directly (bypassing
        RoomStateMachine) changes state in memory but Room.save() rejects the
        persist — is_workflow_active() is False outside RoomStateMachine.apply(),
        so the bypass is blocked before any audit/outbox/RoomStateEvent write."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        initial_events = RoomStateEvent.objects.count()
        assert initial_events == 0

        room.allocate()  # django-fsm sets the field in memory only
        with pytest.raises(ValueError):
            room.save()

        # No partial write: state on disk is unchanged, no audit event created.
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN
        assert RoomStateEvent.objects.count() == 0

    @pytest.mark.django_db
    def test_room_state_machine_creates_audit(self, tenant, property, room_type):
        """Test that RoomStateMachine creates proper audit trail."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Use RoomStateMachine (proper entry point)
        updated_room = RoomStateMachine.apply(
            room, "allocate", actor=None, reason="Test"
        )

        # Verify state changed
        assert updated_room.operational_state == Room.OperationalState.OCCUPIED_CLEAN

        # Verify audit trail was created
        events = RoomStateEvent.objects.filter(room=room)
        assert events.count() == 1

        event = events.first()
        assert event.transition == "allocate"
        assert event.from_state == "vacant_clean"
        assert event.to_state == "occupied_clean"

    @pytest.mark.django_db
    def test_direct_state_assignment_bypasses_everything(self, tenant, property, room_type):
        """Direct attribute assignment + save() is rejected the same way as a
        direct django-fsm call — Room.save() enforces the single entry point
        regardless of how operational_state was changed in memory."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        initial_events = RoomStateEvent.objects.count()
        assert initial_events == 0

        room.operational_state = Room.OperationalState.OCCUPIED_CLEAN
        with pytest.raises(ValueError):
            room.save()

        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN
        assert RoomStateEvent.objects.count() == 0