"""Room state machine tests (M3)."""

import pytest

from apps.rooms.models import Room, RoomStateEvent
from apps.rooms.services import RoomStateMachine
from apps.shared.workflows.runner import TransitionNotAllowed


class TestStateMachine:
    @pytest.mark.django_db
    def test_allocate_vacant_clean_to_occupied_clean(self, tenant, property, room_type):
        """Vacant Clean → Occupied Clean via allocate."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        updated = RoomStateMachine.apply(room, "allocate", actor=None, reason="Guest check-in")

        assert updated.operational_state == Room.OperationalState.OCCUPIED_CLEAN
        assert RoomStateEvent.objects.filter(room=room, transition="allocate").exists()

    @pytest.mark.django_db
    def test_checkout_occupied_clean_to_vacant_dirty(self, tenant, property, room_type):
        """Occupied Clean → Vacant Dirty via checkout."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.OCCUPIED_CLEAN,
        )

        updated = RoomStateMachine.apply(room, "checkout", actor=None, reason="Guest checkout")

        assert updated.operational_state == Room.OperationalState.VACANT_DIRTY
        assert RoomStateEvent.objects.filter(room=room, transition="checkout").exists()

    @pytest.mark.django_db
    def test_clean_vacant_dirty_to_cleaning(self, tenant, property, room_type):
        """Vacant Dirty → Cleaning via clean."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_DIRTY,
        )

        updated = RoomStateMachine.apply(room, "clean", actor=None, reason="Housekeeping assigned")

        assert updated.operational_state == Room.OperationalState.CLEANING
        assert RoomStateEvent.objects.filter(room=room, transition="clean").exists()

    @pytest.mark.django_db
    def test_complete_cleaning_to_inspected(self, tenant, property, room_type):
        """Cleaning → Inspected via complete_cleaning."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.CLEANING,
        )

        updated = RoomStateMachine.apply(
            room, "complete_cleaning", actor=None, reason="Cleaning completed"
        )

        assert updated.operational_state == Room.OperationalState.INSPECTED
        assert RoomStateEvent.objects.filter(room=room, transition="complete_cleaning").exists()

    @pytest.mark.django_db
    def test_approve_inspected_to_vacant_clean(self, tenant, property, room_type):
        """Inspected → Vacant Clean via approve."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.INSPECTED,
        )

        updated = RoomStateMachine.apply(room, "approve", actor=None, reason="Inspection passed")

        assert updated.operational_state == Room.OperationalState.VACANT_CLEAN
        assert RoomStateEvent.objects.filter(room=room, transition="approve").exists()

    @pytest.mark.django_db
    def test_reject_inspected_to_cleaning(self, tenant, property, room_type):
        """Inspected → Cleaning via reject."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.INSPECTED,
        )

        updated = RoomStateMachine.apply(room, "reject", actor=None, reason="Inspection failed")

        assert updated.operational_state == Room.OperationalState.CLEANING
        assert RoomStateEvent.objects.filter(room=room, transition="reject").exists()

    @pytest.mark.django_db
    def test_service_occupied_clean_to_occupied_dirty(self, tenant, property, room_type):
        """Occupied Clean → Occupied Dirty via service."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.OCCUPIED_CLEAN,
        )

        updated = RoomStateMachine.apply(
            room, "service", actor=None, reason="Room service requested"
        )

        assert updated.operational_state == Room.OperationalState.OCCUPIED_DIRTY
        assert RoomStateEvent.objects.filter(room=room, transition="service").exists()

    @pytest.mark.django_db
    def test_service_complete_occupied_dirty_to_occupied_clean(self, tenant, property, room_type):
        """Occupied Dirty → Occupied Clean via service_complete."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.OCCUPIED_DIRTY,
        )

        updated = RoomStateMachine.apply(
            room, "service_complete", actor=None, reason="Service completed"
        )

        assert updated.operational_state == Room.OperationalState.OCCUPIED_CLEAN
        assert RoomStateEvent.objects.filter(room=room, transition="service_complete").exists()

    @pytest.mark.django_db
    def test_defect_vacant_clean_to_out_of_service(self, tenant, property, room_type):
        """Vacant Clean → Out of Service via defect."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        updated = RoomStateMachine.apply(room, "defect", actor=None, reason="Defect found")

        assert updated.operational_state == Room.OperationalState.OUT_OF_SERVICE
        assert RoomStateEvent.objects.filter(room=room, transition="defect").exists()

    @pytest.mark.django_db
    def test_maintenance_occupied_clean_to_out_of_order(self, tenant, property, room_type):
        """Occupied Clean → Out of Order via maintenance."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.OCCUPIED_CLEAN,
        )

        updated = RoomStateMachine.apply(
            room, "maintenance", actor=None, reason="Maintenance needed"
        )

        assert updated.operational_state == Room.OperationalState.OUT_OF_ORDER
        assert RoomStateEvent.objects.filter(room=room, transition="maintenance").exists()

    @pytest.mark.django_db
    def test_restore_out_of_service_to_cleaning(self, tenant, property, room_type):
        """Out of Service → Cleaning via restore (must go through cleaning)."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.OUT_OF_SERVICE,
        )

        updated = RoomStateMachine.apply(room, "restore", actor=None, reason="Repairs completed")

        assert updated.operational_state == Room.OperationalState.CLEANING
        assert RoomStateEvent.objects.filter(room=room, transition="restore").exists()

    @pytest.mark.django_db
    def test_restore_direct_out_of_order_to_vacant_clean(self, tenant, property, room_type):
        """Out of Order → Vacant Clean via restore_direct (no cleaning needed)."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.OUT_OF_ORDER,
        )

        updated = RoomStateMachine.apply(
            room, "restore_direct", actor=None, reason="Maintenance completed"
        )

        assert updated.operational_state == Room.OperationalState.VACANT_CLEAN
        assert RoomStateEvent.objects.filter(room=room, transition="restore_direct").exists()


class TestForbiddenTransitions:
    @pytest.mark.django_db
    def test_vacant_dirty_cannot_go_directly_to_vacant_clean(self, tenant, property, room_type):
        """Vacant Dirty → Vacant Clean is explicitly forbidden."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_DIRTY,
        )

        with pytest.raises(TransitionNotAllowed):
            RoomStateMachine.apply(room, "allocate", actor=None, reason="Invalid transition")

    @pytest.mark.django_db
    def test_invalid_transition_from_vacant_clean(self, tenant, property, room_type):
        """Invalid transition from Vacant Clean."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        with pytest.raises(TransitionNotAllowed):
            RoomStateMachine.apply(room, "invalid_transition", actor=None, reason="Invalid")

    @pytest.mark.django_db
    def test_undefined_transition(self, tenant, property, room_type):
        """Undefined transition raises TransitionNotAllowed."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        with pytest.raises(TransitionNotAllowed):
            RoomStateMachine.apply(room, "nonexistent_transition", actor=None, reason="Invalid")


class TestStateMachineIntegration:
    @pytest.mark.django_db
    def test_full_cleaning_cycle(self, tenant, property, room_type):
        """Test the complete cleaning cycle: VD → Cleaning → Inspected → VC."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_DIRTY,
        )

        # VD → Cleaning
        room = RoomStateMachine.apply(room, "clean", actor=None, reason="Housekeeping")
        assert room.operational_state == Room.OperationalState.CLEANING

        # Cleaning → Inspected
        room = RoomStateMachine.apply(room, "complete_cleaning", actor=None, reason="Cleaning done")
        assert room.operational_state == Room.OperationalState.INSPECTED

        # Inspected → VC
        room = RoomStateMachine.apply(room, "approve", actor=None, reason="Passed inspection")
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN

        # Should have 3 state events
        assert RoomStateEvent.objects.filter(room=room).count() == 3

    @pytest.mark.django_db
    def test_state_event_immutability(self, tenant, property, room_type):
        """RoomStateEvent is append-only."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Apply transition
        RoomStateMachine.apply(room, "allocate", actor=None, reason="Check-in")

        # Verify event was created
        events = RoomStateEvent.objects.filter(room=room)
        assert events.count() == 1
        event = events.first()
        assert event.transition == "allocate"
        assert event.from_state == "vacant_clean"
        assert event.to_state == "occupied_clean"

    @pytest.mark.django_db
    def test_tenant_isolation(self, tenant, property, room_type):
        """State transitions respect tenant isolation."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Apply transition
        RoomStateMachine.apply(room, "allocate", actor=None, reason="Check-in")

        # Verify event is tenant-scoped
        events = RoomStateEvent.objects.filter(room=room)
        assert events.count() == 1
        assert events.first().tenant == tenant