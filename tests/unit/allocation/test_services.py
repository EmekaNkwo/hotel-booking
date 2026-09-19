"""AllocationService unit tests (M11).

Unit tier: SQLite. The pessimistic-locking/row-race proof is Postgres-only
(tests/integration/test_allocation_postgres.py) — this tier proves
candidate selection, scoring determinism, guards, and idempotency.
"""

import pytest
from django.db import IntegrityError
from tests.unit.allocation.conftest import make_booking_line

from apps.allocation.exceptions import BookingLineNotAllocatable, NoEligibleRoom
from apps.allocation.models import AllocationRecord
from apps.allocation.services import AllocationQuery, AllocationService
from apps.bookings.models import BookingStatus
from apps.rooms.models import Room
from apps.rooms.services import RoomStateMachine


@pytest.mark.django_db
class TestAllocateLine:
    def test_assigns_the_only_vacant_room(self, tenant, confirmed_booking_line, vacant_room):
        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-1",
        )
        assert record.room_id == vacant_room.id
        assert record.booking_line_id == confirmed_booking_line.id
        assert record.override is False

    def test_transitions_room_via_room_state_machine(
        self, tenant, confirmed_booking_line, vacant_room
    ):
        AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-2",
        )
        vacant_room.refresh_from_db()
        assert vacant_room.operational_state == Room.OperationalState.OCCUPIED_CLEAN
        assert vacant_room.current_booking_line_id == confirmed_booking_line.id

    def test_updates_booking_line_room_and_status(
        self, tenant, confirmed_booking_line, vacant_room
    ):
        AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-3",
        )
        confirmed_booking_line.refresh_from_db()
        assert confirmed_booking_line.room_id == vacant_room.id
        assert confirmed_booking_line.status == BookingStatus.CHECKED_IN

    def test_never_allocates_a_non_vacant_clean_room(
        self, tenant, property, room_type, confirmed_booking_line
    ):
        Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="OOO-101",
            operational_state=Room.OperationalState.OUT_OF_ORDER,
        )
        with pytest.raises(NoEligibleRoom):
            AllocationService.allocate_line(
                tenant_id=tenant.id,
                booking_line_id=confirmed_booking_line.id,
                idempotency_key="a-4",
            )

    def test_no_eligible_room_leaves_booking_line_untouched(self, tenant, confirmed_booking_line):
        # No Room rows exist at all for this room_type.
        with pytest.raises(NoEligibleRoom):
            AllocationService.allocate_line(
                tenant_id=tenant.id,
                booking_line_id=confirmed_booking_line.id,
                idempotency_key="a-5",
            )
        confirmed_booking_line.refresh_from_db()
        assert confirmed_booking_line.room_id is None
        assert confirmed_booking_line.status == BookingStatus.CONFIRMED
        assert AllocationRecord.objects.count() == 0

    def test_already_allocated_line_raises_and_creates_no_second_record(
        self, tenant, confirmed_booking_line, vacant_room
    ):
        AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-6",
        )
        with pytest.raises(BookingLineNotAllocatable):
            AllocationService.allocate_line(
                tenant_id=tenant.id,
                booking_line_id=confirmed_booking_line.id,
                idempotency_key="a-7",
            )
        assert AllocationRecord.objects.filter(booking_line=confirmed_booking_line).count() == 1

    def test_is_idempotent_per_key(self, tenant, confirmed_booking_line, vacant_room):
        first = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="same-key",
        )
        second = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="same-key",
        )
        assert first.id == second.id
        assert AllocationRecord.objects.count() == 1

    def test_unique_booking_line_constraint_at_db_level(
        self, tenant, confirmed_booking_line, vacant_room
    ):
        """Direct ORM bypass — only the DB constraint can catch a duplicate
        AllocationRecord targeting the same booking line."""
        AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-8",
        )
        with pytest.raises(IntegrityError):
            AllocationRecord.objects.create(
                tenant=tenant,
                property=confirmed_booking_line.booking.property,
                booking_line=confirmed_booking_line,
                room=vacant_room,
            )

    def test_criteria_and_scores_are_persisted(self, tenant, confirmed_booking_line, vacant_room):
        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-9",
        )
        assert record.criteria["booking_line_id"] == confirmed_booking_line.id
        assert record.criteria["candidate_room_ids"] == [vacant_room.id]
        assert str(vacant_room.id) in record.scores
        assert record.reason  # non-empty explanation

    def test_emits_room_allocated_event(self, tenant, confirmed_booking_line, vacant_room):
        from apps.shared.models import OutboxEvent

        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-10",
        )
        assert OutboxEvent.objects.filter(
            event_type="room.allocated", aggregate_id=str(record.id)
        ).exists()

    def test_room_state_changed_event_also_emitted(
        self, tenant, confirmed_booking_line, vacant_room
    ):
        """Two distinct events fire: Room's own room.state_changed (M3,
        automatic) and Allocation's own room.allocated (M11)."""
        from apps.shared.models import OutboxEvent

        AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="a-11",
        )
        assert OutboxEvent.objects.filter(
            event_type="room.state_changed", aggregate_id=str(vacant_room.id)
        ).exists()


@pytest.mark.django_db
class TestPropertyScoping:
    """R0.2 regression: RoomType is tenant-wide, not property-scoped, so
    candidate selection must filter by the booking's own property_id —
    otherwise a multi-property tenant reusing a room-type code/row across
    properties could have a Property-A booking allocated a physical room
    at Property B."""

    @pytest.fixture
    def property2(self, tenant):
        from apps.properties.models import Property

        return Property.objects.create(
            tenant=tenant,
            code="TEST002",
            name="Second Test Hotel",
            status=Property.Status.ACTIVE,
            currency="USD",
            timezone="UTC",
            check_in_time="14:00:00",
            check_out_time="12:00:00",
        )

    def test_vacant_room_at_a_different_property_is_not_a_candidate(
        self, tenant, property2, room_type, confirmed_booking_line
    ):
        """``confirmed_booking_line`` is booked at ``property`` (the default
        fixture). The ONLY vacant room of this (tenant-wide) room_type
        exists at ``property2`` — allocation must find no eligible room,
        never silently cross to the other property."""
        Room.objects.create(
            tenant=tenant,
            property=property2,
            room_type=room_type,
            code="P2-101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        with pytest.raises(NoEligibleRoom):
            AllocationService.allocate_line(
                tenant_id=tenant.id,
                booking_line_id=confirmed_booking_line.id,
                idempotency_key="prop-scope-1",
            )
        confirmed_booking_line.refresh_from_db()
        assert confirmed_booking_line.room_id is None
        assert AllocationRecord.objects.count() == 0

    def test_same_property_room_is_chosen_even_when_a_better_scored_room_exists_elsewhere(
        self, tenant, property, property2, room_type, confirmed_booking_line
    ):
        """A multi-property tenant with the same room-type code at both
        properties: even a room type + tenant match at Property 2 must
        never be selected for a Property-1 booking, regardless of
        candidate count or ordering."""
        own_property_room = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        Room.objects.create(
            tenant=tenant,
            property=property2,
            room_type=room_type,
            code="P2-101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="prop-scope-2",
        )
        assert record.room_id == own_property_room.id
        assert record.property_id == property.id


@pytest.mark.django_db
class TestDeterministicScoring:
    def test_same_inputs_produce_the_same_room(self, tenant, property, room_type, stay):
        Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="201",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="202",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        line_a = make_booking_line(
            tenant,
            property,
            room_type,
            stay,
            guest_email="a@example.com",
            key_prefix="det-a",
        )
        record_a = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=line_a.id,
            idempotency_key="det-alloc-a",
        )
        # Lowest room id wins deterministically among equally-eligible rooms.
        lowest_room_id = Room.objects.filter(room_type=room_type).order_by("id").first().id
        assert record_a.room_id == lowest_room_id

    def test_stay_continuity_beats_the_tie_break(self, tenant, property, room_type, stay):
        room1 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="301",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        room2 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="302",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        assert room1.id < room2.id  # tie-break would normally pick room1

        first_line = make_booking_line(
            tenant,
            property,
            room_type,
            stay,
            guest_email="repeat@example.com",
            key_prefix="cont-1",
        )
        first_record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=first_line.id,
            idempotency_key="cont-alloc-1",
        )
        assert first_record.room_id == room1.id  # tie-break picked the lowest id

        # Cycle room1 back to vacant so it's a real candidate again.
        room1.refresh_from_db()
        RoomStateMachine.apply(room1, "checkout")
        RoomStateMachine.apply(room1, "clean")
        RoomStateMachine.apply(room1, "complete_cleaning")
        RoomStateMachine.apply(room1, "approve")

        second_line = make_booking_line(
            tenant,
            property,
            room_type,
            stay,
            guest_email="repeat@example.com",
            key_prefix="cont-2",
        )
        second_record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=second_line.id,
            idempotency_key="cont-alloc-2",
        )
        assert second_record.room_id == room1.id  # stay continuity, not the tie-break
        assert "stay continuity" in second_record.reason


@pytest.mark.django_db
class TestDeterministicLockOrder:
    """R0.5 regression: candidate ROOMS must be locked in a fixed,
    guest-independent order (ascending room_id) — never in guest-specific
    score order, which previously let two different guests' preferences
    cross and deadlock (found in the red-team review)."""

    def test_lock_order_is_ascending_room_id_regardless_of_guest_preference(
        self, monkeypatch, tenant, property, room_type, stay
    ):
        room1 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="401",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        room2 = Room.objects.create(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="402",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )
        assert room1.id < room2.id

        # Give a guest a stay-continuity preference for the HIGHER room id
        # (room2) — the opposite of the deterministic tie-break — so this
        # guest's score-order candidate list is [room2, room1], reversed
        # from ascending id.
        continuity_line = make_booking_line(
            tenant, property, room_type, stay, guest_email="prefers-room2@example.com",
            key_prefix="lock-order-setup",
        )
        # Occupy room1 first so allocation is forced onto room2, giving that
        # guest a real prior stay in room2.
        RoomStateMachine.apply(room1, "allocate", reason="occupy for setup")
        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=continuity_line.id,
            idempotency_key="lock-order-setup-alloc",
        )
        assert record.room_id == room2.id
        # Cycle both rooms back to vacant for the real test below.
        room2.refresh_from_db()
        RoomStateMachine.apply(room2, "checkout")
        RoomStateMachine.apply(room2, "clean")
        RoomStateMachine.apply(room2, "complete_cleaning")
        RoomStateMachine.apply(room2, "approve")
        room1.refresh_from_db()
        RoomStateMachine.apply(room1, "checkout")
        RoomStateMachine.apply(room1, "clean")
        RoomStateMachine.apply(room1, "complete_cleaning")
        RoomStateMachine.apply(room1, "approve")

        # Spy on Room.objects.select_for_update().get(...) to record the
        # exact sequence of room ids locked during allocation.
        locked_order: list[int] = []
        original_select_for_update = Room.objects.select_for_update

        def _spy_select_for_update(*args, **kwargs):
            qs = original_select_for_update(*args, **kwargs)
            original_get = qs.get

            def _spy_get(*a, **k):
                obj = original_get(*a, **k)
                locked_order.append(obj.pk)
                return obj

            qs.get = _spy_get
            return qs

        monkeypatch.setattr(Room.objects, "select_for_update", _spy_select_for_update)

        # This guest has stay continuity for room2 (score order [room2,
        # room1] — the OLD code would have locked in THAT order). The fix
        # must lock ascending (room1, room2) regardless.
        preference_line = make_booking_line(
            tenant, property, room_type, stay, guest_email="prefers-room2@example.com",
            key_prefix="lock-order-test",
        )
        AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=preference_line.id,
            idempotency_key="lock-order-test-alloc",
        )

        assert locked_order == sorted(locked_order), (
            f"rooms were locked out of ascending-id order: {locked_order!r} — "
            "this is guest-preference-dependent locking, exactly the pattern "
            "that produced the AB-BA deadlock in review"
        )
        assert locked_order == [room1.id, room2.id]


@pytest.mark.django_db
class TestAllocationQuery:
    def test_by_booking_line(self, tenant, confirmed_booking_line, vacant_room):
        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="q-1",
        )
        assert AllocationQuery.by_booking_line(confirmed_booking_line) == record

    def test_by_room(self, tenant, confirmed_booking_line, vacant_room):
        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="q-2",
        )
        assert list(AllocationQuery.by_room(vacant_room)) == [record]

    def test_for_property(self, tenant, property, confirmed_booking_line, vacant_room):
        record = AllocationService.allocate_line(
            tenant_id=tenant.id,
            booking_line_id=confirmed_booking_line.id,
            idempotency_key="q-3",
        )
        assert list(AllocationQuery.for_property(property)) == [record]
