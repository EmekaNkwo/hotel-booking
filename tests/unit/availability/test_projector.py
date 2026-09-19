"""RoomStateProjector unit tests (M7 scope item 11).

Consumes the REAL ``room.state_changed`` events the M3 room state machine
already emits — relayed through the existing ``OutboxRelay`` (M1.3), exactly
as production would. No ``room.type_retired`` producer exists anywhere in
the codebase, so it is never exercised here (M7 scope item 3/11).
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.availability.models import AvailabilitySlot
from apps.availability.projectors import PROJECTION_NAME, RoomStateProjector
from apps.availability.services import AvailabilityService
from apps.rooms.models import Room
from apps.rooms.services import RoomStateMachine
from apps.shared.models import ProjectionState, ProjectionStatus
from apps.shared.services.outbox import OutboxRelay

HORIZON_DAYS = 10


@pytest.fixture
def room(tenant, property, room_type):
    return Room.objects.create(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="101",
        operational_state=Room.OperationalState.VACANT_CLEAN,
    )


@pytest.fixture
def today():
    return timezone.now().date()


@pytest.fixture(autouse=True)
def _initialize_capacity(tenant, property, room_type, today):
    AvailabilityService.initialize_horizon(
        tenant_id=tenant.id,
        property_id=property.id,
        room_type_id=room_type.id,
        total_units=5,
        start_date=today,
        horizon_days=HORIZON_DAYS,
    )


def _relay_and_process() -> int:
    OutboxRelay().publish_batch()
    return RoomStateProjector.process_batch(horizon_days=HORIZON_DAYS)


def _slot_out_of_service(tenant, property, room_type, on_date):
    return AvailabilitySlot.objects.get(
        tenant_id=tenant.id,
        property_id=property.id,
        room_type_id=room_type.id,
        business_date=on_date,
    ).out_of_service


@pytest.mark.django_db
class TestRoomStateProjector:
    def test_defect_increments_out_of_service_across_the_horizon(
        self, tenant, property, room_type, room, today
    ):
        RoomStateMachine.apply(room, "defect")
        processed = _relay_and_process()

        assert processed == 1
        assert _slot_out_of_service(tenant, property, room_type, today) == 1
        assert _slot_out_of_service(tenant, property, room_type, today + timedelta(days=9)) == 1

    def test_restore_from_oos_decrements_back_to_zero(
        self, tenant, property, room_type, room, today
    ):
        RoomStateMachine.apply(room, "defect")
        _relay_and_process()
        assert _slot_out_of_service(tenant, property, room_type, today) == 1

        RoomStateMachine.apply(room, "restore")  # OOS -> CLEANING (leaves the unsellable set)
        processed = _relay_and_process()

        assert processed == 1
        assert _slot_out_of_service(tenant, property, room_type, today) == 0

    def test_maintenance_ooo_also_increments_out_of_service(
        self, tenant, property, room_type, room, today
    ):
        RoomStateMachine.apply(room, "allocate")  # vacant_clean -> occupied_clean
        _relay_and_process()
        assert (
            _slot_out_of_service(tenant, property, room_type, today) == 0
        )  # sellable transition, no-op

        RoomStateMachine.apply(room, "maintenance")  # occupied_clean -> out_of_order
        processed = _relay_and_process()

        assert processed == 1
        assert _slot_out_of_service(tenant, property, room_type, today) == 1

    def test_transitions_that_stay_inside_the_sellable_set_are_a_no_op(
        self, tenant, property, room_type, room, today
    ):
        RoomStateMachine.apply(room, "allocate")  # vacant_clean -> occupied_clean
        processed = _relay_and_process()

        assert processed == 1  # the event WAS applied...
        assert _slot_out_of_service(tenant, property, room_type, today) == 0  # ...as a no-op

    def test_replay_of_an_already_processed_event_is_a_no_op(
        self, tenant, property, room_type, room, today
    ):
        RoomStateMachine.apply(room, "defect")
        _relay_and_process()
        assert _slot_out_of_service(tenant, property, room_type, today) == 1

        # Re-running the batch with nothing new pending must not re-apply.
        processed_again = RoomStateProjector.process_batch(horizon_days=HORIZON_DAYS)
        assert processed_again == 0
        assert _slot_out_of_service(tenant, property, room_type, today) == 1

    def test_checkpoint_advances_and_is_persisted(self, tenant, property, room_type, room, today):
        RoomStateMachine.apply(room, "defect")
        _relay_and_process()

        state = ProjectionState.objects.get(projection_name=PROJECTION_NAME)
        assert state.status == ProjectionStatus.ACTIVE
        assert state.last_event_id != ""
        assert state.last_processed_at is not None
