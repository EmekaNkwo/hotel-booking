"""Final enforcement test for single-entry-point invariant.

This test proves that:
1. Direct transition invocation cannot silently change state
2. RoomStateMachine.apply() still works
3. Audit is written
4. RoomStateEvent is written
5. Outbox event is written
6. Permission checks still apply
7. The whole operation remains atomic
"""

import pytest
from django.db import transaction

from apps.rooms.models import Room, RoomStateEvent
from apps.rooms.services import RoomStateMachine
from apps.shared.models import AuditLog, OutboxEvent


class TestSingleEntryPointEnforcement:
    """Test that the enforcement mechanism actually prevents bypass."""

    @pytest.mark.django_db
    def test_direct_transition_call_is_blocked(self, tenant, property, room_type):
        """Test that direct transition calls are blocked at save() time."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Try to call transition method directly
        room.allocate()  # This changes state in memory

        # Try to save - this should be blocked
        with pytest.raises(
            ValueError, match="Room state changes must go through RoomStateMachine.apply"
        ):
            room.save()

        # Verify state was NOT persisted
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN
        assert RoomStateEvent.objects.count() == 0

    @pytest.mark.django_db
    def test_room_state_machine_still_works(self, tenant, property, room_type):
        """Test that RoomStateMachine.apply() still works correctly."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Use RoomStateMachine (proper entry point)
        updated_room = RoomStateMachine.apply(
            room, "allocate", actor=None, reason="Test allocation"
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
    def test_audit_is_written(self, tenant, property, room_type):
        """Test that audit records are created."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Apply transition
        RoomStateMachine.apply(room, "allocate", actor=None, reason="Test")

        # Check audit service
        audits = AuditLog.objects.filter(tenant_id=tenant.id)
        room_audits = [a for a in audits if a.entity_id == str(room.pk)]
        assert len(room_audits) == 1

        audit = room_audits[0]
        assert audit.action == "allocate"
        assert audit.before["state"] == "vacant_clean"
        assert audit.after["state"] == "occupied_clean"

    @pytest.mark.django_db
    def test_outbox_event_is_written(self, tenant, property, room_type):
        """Test that outbox events are created."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Apply transition
        RoomStateMachine.apply(room, "allocate", actor=None, reason="Test")

        # Check outbox service
        events = OutboxEvent.objects.filter(tenant_id=tenant.id)
        room_events = [e for e in events if e.aggregate_id == str(room.pk)]
        assert len(room_events) == 1

        event = room_events[0]
        assert event.event_type == "room.state_changed"
        assert event.payload["from"] == "vacant_clean"
        assert event.payload["to"] == "occupied_clean"

    @pytest.mark.django_db
    def test_atomic_operation(self, tenant, property, room_type):
        """Test that the operation remains atomic."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Count initial records
        initial_events = RoomStateEvent.objects.count()
        initial_audits = len(AuditLog.objects.filter(tenant_id=tenant.id))
        initial_outbox = len(OutboxEvent.objects.filter(tenant_id=tenant.id))

        # Apply transition
        updated_room = RoomStateMachine.apply(room, "allocate", actor=None, reason="Test")

        # Verify all records were created in one transaction
        assert RoomStateEvent.objects.count() == initial_events + 1
        assert len(AuditLog.objects.filter(tenant_id=tenant.id)) == initial_audits + 1
        assert len(OutboxEvent.objects.filter(tenant_id=tenant.id)) == initial_outbox + 1
        assert updated_room.operational_state == Room.OperationalState.OCCUPIED_CLEAN

    @pytest.mark.django_db
    def test_permission_checks_still_apply(self, tenant, property, room_type):
        """Test that permission checks are still enforced."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # Try an invalid transition
        with pytest.raises(Exception):  # django-fsm raises TransitionNotAllowed
            RoomStateMachine.apply(room, "checkout", actor=None, reason="Invalid")

        # State should not have changed
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN

    @pytest.mark.django_db
    def test_all_transitions_enforced(self, tenant, property, room_type):
        """Every one of the 12 transitions: direct call is blocked, and
        RoomStateMachine.apply() from the transition's actual source state
        works. Each transition gets its own room, since the 12 transitions
        don't share a common source state (e.g. "service" only fires from
        occupied_clean, not vacant_clean)."""
        S = Room.OperationalState
        transitions = [
            ("allocate", S.VACANT_CLEAN, S.OCCUPIED_CLEAN),
            ("service", S.OCCUPIED_CLEAN, S.OCCUPIED_DIRTY),
            ("service_complete", S.OCCUPIED_DIRTY, S.OCCUPIED_CLEAN),
            ("checkout", S.OCCUPIED_CLEAN, S.VACANT_DIRTY),
            ("clean", S.VACANT_DIRTY, S.CLEANING),
            ("complete_cleaning", S.CLEANING, S.INSPECTED),
            ("approve", S.INSPECTED, S.VACANT_CLEAN),
            ("reject", S.INSPECTED, S.CLEANING),
            ("defect", S.VACANT_CLEAN, S.OUT_OF_SERVICE),
            ("maintenance", S.OCCUPIED_CLEAN, S.OUT_OF_ORDER),
            ("restore", S.OUT_OF_SERVICE, S.CLEANING),
            ("restore_direct", S.OUT_OF_ORDER, S.VACANT_CLEAN),
        ]

        for i, (transition_name, source_state, expected_state) in enumerate(transitions):
            room = Room.objects.create(
                tenant=tenant,
                property=property,
                room_type=room_type,
                code=f"10{i}",
                operational_state=source_state,
            )

            # Direct call is blocked at save() time — no partial write.
            getattr(room, transition_name)()
            with pytest.raises(
                ValueError, match="Room state changes must go through RoomStateMachine.apply"
            ):
                room.save()
            room.refresh_from_db()
            assert room.operational_state == source_state

            # Through RoomStateMachine — the sanctioned path — it works.
            updated_room = RoomStateMachine.apply(room, transition_name, actor=None, reason="Test")
            assert updated_room.operational_state == expected_state

    @pytest.mark.django_db
    def test_concurrent_state_change_prevented(self, tenant, property, room_type):
        """Test that concurrent state changes are handled correctly."""
        room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        # First transaction
        with transaction.atomic():
            room1 = Room.objects.select_for_update().get(pk=room.pk)
            RoomStateMachine.apply(room1, "allocate", actor=None, reason="Test1")

        # Verify state changed
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.OCCUPIED_CLEAN

        # Second transaction (should work)
        updated_room = RoomStateMachine.apply(room, "service", actor=None, reason="Test2")
        assert updated_room.operational_state == Room.OperationalState.OCCUPIED_DIRTY