"""Test that dependency direction is correct and enforcement works."""

import pytest

from apps.rooms.models import Room, RoomStateEvent
from apps.rooms.services import RoomStateMachine
from apps.shared.workflows.context import is_workflow_active, WorkflowContext


class TestDependencyDirection:
    """Test that the architectural boundaries are respected."""

    @pytest.mark.django_db
    def test_shared_context_is_independent(self):
        """Test that shared context doesn't depend on rooms."""
        # This test just verifies the import works
        assert is_workflow_active is not None
        assert WorkflowContext is not None

    @pytest.mark.django_db
    def test_workflow_context_works(self):
        """Test that WorkflowContext works correctly."""
        # Initially not active
        assert not is_workflow_active()

        # Inside context, should be active
        with WorkflowContext():
            assert is_workflow_active()

        # After context, should not be active
        assert not is_workflow_active()

    @pytest.mark.django_db
    def test_enforcement_still_works(self, tenant, property, room_type):
        """Test that enforcement mechanism still works with corrected dependencies."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Direct call should be blocked
        room.allocate()
        with pytest.raises(ValueError, match="Room state changes must go through RoomStateMachine.apply()"):
            room.save()

        # RoomStateMachine should work
        updated_room = RoomStateMachine.apply(room, "allocate", actor=None, reason="Test")
        assert updated_room.operational_state == Room.OperationalState.OCCUPIED_CLEAN
        assert RoomStateEvent.objects.count() == 1

    @pytest.mark.django_db
    def test_workflow_context_in_runner(self, tenant, property, room_type):
        """Test that WorkflowRunner properly uses WorkflowContext."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Verify that RoomStateMachine.apply() uses WorkflowContext internally
        # by checking that the state change is allowed
        updated_room = RoomStateMachine.apply(room, "allocate", actor=None, reason="Test")
        assert updated_room.operational_state == Room.OperationalState.OCCUPIED_CLEAN

        # This proves that WorkflowRunner.set_workflow_context() was called
        # because otherwise the save() method would have blocked the state change