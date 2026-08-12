"""Room test fixtures."""

import pytest

from apps.rooms.models import RoomType, Room


@pytest.fixture
def room_type(tenant):
    """RoomType fixture."""
    return RoomType.objects.create(
        tenant=tenant,
        code="STD-KING",
        name="Standard King",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
        attributes={"bed_type": "king"},
    )


@pytest.fixture
def room(tenant, property, room_type):
    """Room fixture."""
    return Room.objects.create(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="101",
        operational_state=Room.OperationalState.VACANT_CLEAN,
    )


@pytest.fixture
def room_a(tenant, property, room_type):
    """First room for connection tests."""
    return Room.objects.create(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="101",
    )


@pytest.fixture
def room_b(tenant, property, room_type):
    """Second room for connection tests."""
    return Room.objects.create(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="102",
    )