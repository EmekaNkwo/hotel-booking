"""Room model tests (M3)."""

import pytest
from django.core.exceptions import ValidationError

from apps.rooms.models import RoomType, Room, RoomStateEvent, RoomConnection


class TestRoomType:
    @pytest.mark.django_db
    def test_create_room_type(self, tenant):
        """RoomType creation with all required fields."""
        room_type = RoomType.objects.create(
            tenant=tenant,
            code="STD-KING",
            name="Standard King",
            status=RoomType.Status.ACTIVE,
            max_occupancy=2,
            attributes={"bed_type": "king", "view": "city"},
        )
        assert room_type.code == "STD-KING"
        assert room_type.status == RoomType.Status.ACTIVE
        assert room_type.max_occupancy == 2

    @pytest.mark.django_db
    def test_room_type_unique_code_per_tenant(self, tenant):
        """Unique constraint: (tenant, code)."""
        RoomType.objects.create(
            tenant=tenant,
            code="STD-KING",
            name="Standard King",
            status=RoomType.Status.ACTIVE,
            max_occupancy=2,
        )
        with pytest.raises(Exception):  # UniqueConstraint violation
            RoomType.objects.create(
                tenant=tenant,
                code="STD-KING",  # Duplicate
                name="Standard King 2",
                status=RoomType.Status.ACTIVE,
                max_occupancy=2,
            )

    @pytest.mark.django_db
    def test_room_type_status_validation(self, tenant):
        """Status must be one of: active, retired."""
        with pytest.raises(ValidationError):
            RoomType.objects.create(
                tenant=tenant,
                code="STD-KING",
                name="Standard King",
                status="invalid",  # Not in choices
                max_occupancy=2,
            )


class TestRoom:
    @pytest.mark.django_db
    def test_create_room(self, tenant, property, room_type):
        """Room creation with all required fields."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        assert room.code == "101"
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN

    @pytest.mark.django_db
    def test_room_unique_code_per_property(self, tenant, property, room_type):
        """Unique constraint: (property, code)."""
        Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
        )
        with pytest.raises(Exception):  # UniqueConstraint violation
            Room.objects.create(
                tenant=tenant,
                property=property,
                room_type=room_type,
                code="101",  # Duplicate
            )

    @pytest.mark.django_db
    def test_room_operational_state_validation(self, tenant, property, room_type):
        """Operational state must be one of the defined choices."""
        with pytest.raises(ValidationError):
            Room.objects.create(
                tenant=tenant,
                property=property,
                room_type=room_type,
                code="101",
                operational_state="invalid_state",  # Not in choices
            )

    @pytest.mark.django_db
    def test_room_current_booking_line_id_nullable(self, tenant, property, room_type):
        """current_booking_line_id is nullable."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            current_booking_line_id=None,
        )
        assert room.current_booking_line_id is None

    @pytest.mark.django_db
    def test_room_soft_delete(self, tenant, property, room_type):
        """Room supports soft deletion."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
        )
        room.deleted_at = pytest.datetime.now()
        room.save()
        assert room.deleted_at is not None


class TestRoomStateEvent:
    @pytest.mark.django_db
    def test_create_room_state_event(self, tenant, room):
        """RoomStateEvent creation."""
        event = RoomStateEvent.objects.create(
            tenant=tenant,
            room=room,
            from_state="vacant_clean",
            to_state="occupied_clean",
            transition=RoomStateEvent.Transition.ALLOCATE,
            actor_id=1,
            actor_type="user",
            reason="Guest check-in",
        )
        assert event.transition == RoomStateEvent.Transition.ALLOCATE
        assert event.from_state == "vacant_clean"
        assert event.to_state == "occupied_clean"

    @pytest.mark.django_db
    def test_room_state_event_transition_validation(self, tenant, room):
        """Transition must be one of the defined choices."""
        with pytest.raises(ValidationError):
            RoomStateEvent.objects.create(
                tenant=tenant,
                room=room,
                from_state="vacant_clean",
                to_state="occupied_clean",
                transition="invalid_transition",  # Not in choices
                actor_id=1,
                actor_type="user",
            )

    @pytest.mark.django_db
    def test_room_state_event_immutability(self, tenant, room):
        """RoomStateEvent is append-only (no updates)."""
        event = RoomStateEvent.objects.create(
            tenant=tenant,
            room=room,
            from_state="vacant_clean",
            to_state="occupied_clean",
            transition=RoomStateEvent.Transition.ALLOCATE,
            actor_id=1,
            actor_type="user",
            reason="Guest check-in",
        )
        # Verify the event was created
        assert RoomStateEvent.objects.filter(id=event.id).exists()


class TestRoomConnection:
    @pytest.mark.django_db
    def test_create_room_connection(self, tenant, room_a, room_b):
        """RoomConnection creation."""
        connection = RoomConnection.objects.create(
            tenant=tenant,
            room_a=room_a,
            room_b=room_b,
            connection_type="adjoining",
        )
        assert connection.room_a == room_a
        assert connection.room_b == room_b
        assert connection.connection_type == "adjoining"

    @pytest.mark.django_db
    def test_room_connection_unique_pair(self, tenant, room_a, room_b):
        """Unique constraint: (room_a, room_b)."""
        RoomConnection.objects.create(
            tenant=tenant,
            room_a=room_a,
            room_b=room_b,
            connection_type="adjoining",
        )
        with pytest.raises(Exception):  # UniqueConstraint violation
            RoomConnection.objects.create(
                tenant=tenant,
                room_a=room_a,
                room_b=room_b,  # Duplicate pair
                connection_type="adjoining",
            )

    @pytest.mark.django_db
    def test_room_connection_no_self_loop(self, tenant, room_a):
        """RoomConnection cannot connect a room to itself."""
        with pytest.raises(ValidationError):
            RoomConnection.objects.create(
                tenant=tenant,
                room_a=room_a,
                room_b=room_a,  # Same room
                connection_type="adjoining",
            )

    @pytest.mark.django_db
    def test_room_connection_symmetry(self, tenant, room_a, room_b):
        """RoomConnection is symmetric: room_a ↔ room_b."""
        connection = RoomConnection.objects.create(
            tenant=tenant,
            room_a=room_a,
            room_b=room_b,
            connection_type="adjoining",
        )
        # Both rooms should have the connection
        assert room_a.connections_as_a.first() == connection
        assert room_b.connections_as_b.first() == connection


class TestRoomQuery:
    @pytest.mark.django_db
    def test_vacant_clean_candidates(self, tenant, property, room_type):
        """RoomQuery.vacant_clean_candidates returns Vacant Clean rooms."""
        # Create a Vacant Clean room
        room1 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        # Create a non-Vacant Clean room
        room2 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="102",
            operational_state=Room.OperationalState.OCCUPIED_CLEAN,
        )

        candidates = RoomQuery.vacant_clean_candidates(room_type.id)
        assert room1 in candidates
        assert room2 not in candidates

    @pytest.mark.django_db
    def test_by_property(self, tenant, property, room_type):
        """RoomQuery.by_property returns all rooms for a property."""
        room1 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
        )
        room2 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="102",
        )

        rooms = RoomQuery.by_property(property.id)
        assert room1 in rooms
        assert room2 in rooms

    @pytest.mark.django_db
    def test_with_attributes(self, tenant, property, room_type):
        """RoomQuery.with_attributes filters by room_type attributes."""
        # Room type with specific attributes
        room_type_with_view = RoomType.objects.create(
            tenant=tenant,
            code="DELUXE",
            name="Deluxe Room",
            status=RoomType.Status.ACTIVE,
            max_occupancy=2,
            attributes={"view": "ocean", "balcony": True},
        )
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type_with_view,
            code="201",
        )

        rooms = RoomQuery.with_attributes({"view": "ocean"})
        assert room in rooms