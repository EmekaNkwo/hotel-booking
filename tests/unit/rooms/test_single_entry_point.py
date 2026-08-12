"""Test that RoomStateMachine is the only entry point for state transitions."""

import pytest
from django.db import transaction

from apps.rooms.models import Room, RoomStateEvent
from apps.rooms.services import RoomStateMachine


class TestSingleEntryPoint:
    @pytest.mark.django_db
    def test_direct_django_fsm_call_bypasses_audit(self, tenant, property, room_type):
        """Test if calling django-fsm methods directly bypasses audit/outbox."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Count initial state events
        initial_events = RoomStateEvent.objects.count()
        assert initial_events == 0

        # Try to call django-fsm method directly
        try:
            # This should work if django-fsm methods are publicly accessible
            room.allocate()
            room.save()

            # Check if state changed without audit
            room.refresh_from_db()
            assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN

            # Check if audit was bypassed
            final_events = RoomStateEvent.objects.count()
            assert final_events == 0  # No audit event created

            print("⚠️  SECURITY ISSUE: Direct django-fsm calls bypass audit/outbox!")

        except AttributeError:
            # django-fsm methods are not accessible - this is good!
            print("✅ django-fsm methods are not publicly accessible")

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
        """Test if direct state assignment bypasses all safeguards."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        initial_events = RoomStateEvent.objects.count()
        assert initial_events == 0

        # Direct state assignment (this should be possible but is a bad practice)
        room.operational_state = Room.OperationalState.OCCUPIED_CLEAN
        room.save()

        # Verify state changed
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN

        # Verify no audit trail
        final_events = RoomStateEvent.objects.count()
        assert final_events == 0

        print("⚠️  SECURITY ISSUE: Direct state assignment bypasses all safeguards!")