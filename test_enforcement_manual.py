#!/usr/bin/env python
"""Manual test script to verify enforcement mechanism."""

import os
import sys
import django

# Setup Django
sys.path.insert(0, 'c:\\Users\\VERGIO\\Documents\\code_apps\\django-projects\\hotel-booking')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.rooms.models import Room, RoomStateEvent
from apps.rooms.services import RoomStateMachine
from apps.tenants.models import Tenant
from apps.properties.models import Property
from apps.rooms.models import RoomType
from apps.shared.workflows.context import is_workflow_active


def test_enforcement():
    """Test the enforcement mechanism."""
    print("Creating test data...")

    # Create tenant
    tenant = Tenant.objects.create(name="Test Tenant", code="TEST")

    # Create property
    property = Property.objects.create(
        tenant=tenant,
        name="Test Property",
        code="TPROP",
        address="123 Test St",
        city="Testville",
        state="TS",
        country="US",
        timezone="UTC"
    )

    # Create room type
    room_type = RoomType.objects.create(
        tenant=tenant,
        code="STD",
        name="Standard Room"
    )

    # Create room
    room = Room.objects.create(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="101",
        operational_state=Room.OperationalState.VACANT_CLEAN,
    )

    print(f"Created room {room.pk} in state {room.operational_state}")

    # Test 1: Direct transition call should be blocked
    print("\n=== Test 1: Direct transition call ===")
    try:
        room.allocate()  # This changes state in memory
        print(f"Called allocate(), state in memory: {room.operational_state}")
        room.save()  # This should be blocked
        print("ERROR: Save should have been blocked!")
        return False
    except ValueError as e:
        print(f"✅ SUCCESS: Save blocked with error: {e}")
        room.refresh_from_db()
        print(f"State after failed save: {room.operational_state}")

    # Test 2: RoomStateMachine should work
    print("\n=== Test 2: RoomStateMachine.apply() ===")
    try:
        updated_room = RoomStateMachine.apply(room, "allocate", actor=None, reason="Test")
        print(f"✅ SUCCESS: State changed to {updated_room.operational_state}")

        # Check audit trail
        events = RoomStateEvent.objects.filter(room=room)
        print(f"Audit events created: {events.count()}")
        if events.count() == 1:
            event = events.first()
            print(f"Event: {event.transition} from {event.from_state} to {event.to_state}")

        return True
    except Exception as e:
        print(f"ERROR: RoomStateMachine failed: {e}")
        return False


if __name__ == "__main__":
    try:
        success = test_enforcement()
        if success:
            print("\n🎉 All tests passed!")
            sys.exit(0)
        else:
            print("\n❌ Some tests failed!")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)