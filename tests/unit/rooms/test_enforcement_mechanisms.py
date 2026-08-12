"""Test different enforcement mechanisms for single-entry-point invariant."""

import pytest
from django.db import transaction

from apps.rooms.models import Room, RoomStateEvent
from apps.rooms.services import RoomStateMachine


class TestEnforcementMechanisms:
    """Test different ways to enforce single-entry-point invariant."""

    @pytest.mark.django_db
    def test_current_bypass_vulnerability(self, tenant, property, room_type):
        """Demonstrate the current vulnerability."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Direct call bypasses everything
        initial_events = RoomStateEvent.objects.count()
        assert initial_events == 0

        # This should NOT be allowed but currently is
        room.allocate()
        room.save()

        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN
        assert RoomStateEvent.objects.count() == 0  # No audit!

    @pytest.mark.django_db
    def test_proper_path_works(self, tenant, property, room_type):
        """Verify the proper path works correctly."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Proper path through RoomStateMachine
        updated_room = RoomStateMachine.apply(
            room, "allocate", actor=None, reason="Test"
        )

        assert updated_room.operational_state == Room.OperationalState.OCCUPIED_CLEAN
        assert RoomStateEvent.objects.count() == 1  # Audit created!

    @pytest.mark.django_db
    def test_save_method_guard_approach(self, tenant, property, room_type):
        """Test if we can guard in save() method."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Track state before transition
        original_state = room.operational_state

        # Call transition method (changes state in memory)
        room.allocate()

        # State changed in memory but not saved yet
        assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN
        assert original_state == Room.OperationalState.VACANT_CLEAN

        # The save() method could detect this and reject
        # We need a way to mark "this change came through WorkflowRunner"

    @pytest.mark.django_db
    def test_workflow_runner_marker_approach(self, tenant, property, room_type):
        """Test using a marker to track proper workflow execution."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Idea: WorkflowRunner sets a flag before calling transition
        # Then save() checks if the flag is set
        # If not set, reject the save

        # This would require modifying WorkflowRunner or Room model

    @pytest.mark.django_db
    def test_internal_method_approach(self, tenant, property, room_type):
        """Test making transition methods truly internal."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Idea: Don't use django-fsm decorators on public methods
        # Instead, create internal methods that WorkflowRunner calls
        # Public methods would be on RoomStateMachine only

        # This would require significant refactoring
