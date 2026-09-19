"""AvailabilityService / AvailabilityQuery / InventoryService unit tests (M7).

Unit tier: SQLite. Pessimistic locking (``select_for_update``) is a no-op on
SQLite but the invariant checks, all-or-nothing multi-night behavior, and
idempotency are all backend-agnostic Python logic exercised here in full;
the REAL concurrency proof is Postgres-only (tests/integration).
"""

from datetime import timedelta

import pytest
from django.conf import settings

from apps.availability.exceptions import InsufficientAvailability
from apps.availability.models import AvailabilitySlot, Channel
from apps.availability.services import AvailabilityQuery, AvailabilityService, InventoryService
from apps.shared.value_objects import DateRange


@pytest.mark.django_db
class TestInitializeHorizon:
    def test_creates_a_slot_per_day_of_the_horizon(
        self, tenant, property, room_type, horizon_start
    ):
        created = AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=10,
            start_date=horizon_start,
            horizon_days=30,
        )
        assert created == 30
        assert (
            AvailabilitySlot.objects.filter(
                tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
            ).count()
            == 30
        )

    def test_total_units_is_explicit_never_derived_from_room_count(
        self, tenant, property, room_type, horizon_start
    ):
        """Room.objects.count() is zero here — capacity still opens because
        Availability owns sellable room-type capacity as an explicit input,
        never a physical room count (DR-05)."""
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=25,
            start_date=horizon_start,
            horizon_days=1,
        )
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
        )
        assert slot.total_units == 25
        assert slot.remaining == 25

    def test_defaults_to_the_configured_horizon_setting(
        self, tenant, property, room_type, horizon_start
    ):
        created = AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
        )
        assert created == settings.AVAILABILITY_HORIZON_DAYS

    def test_is_idempotent_per_date_existing_slots_untouched(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=10,
            start_date=horizon_start,
            horizon_days=5,
        )
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            business_date=horizon_start,
        )
        slot_pk_id = slot.id

        # Consume some capacity, then re-run initialize over an overlapping,
        # wider window — the already-initialized date must not be reset.
        dr = DateRange(horizon_start, horizon_start + timedelta(days=1))
        InventoryService.sell(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=3,
            idempotency_key="init-idem-1",
        )
        second_created = AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=10,
            start_date=horizon_start,
            horizon_days=10,
        )
        assert second_created == 5  # only the 5 NEW dates (day 5..9)
        slot.refresh_from_db()
        assert slot.id == slot_pk_id
        assert slot.sold == 3  # untouched by the second call


@pytest.mark.django_db
class TestAvailabilityQuery:
    def test_remaining_for_range_reflects_consumption(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=4,
            start_date=horizon_start,
            horizon_days=5,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=2))
        InventoryService.sell(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=1,
            idempotency_key="q-1",
        )
        remaining = AvailabilityQuery.remaining_for_range(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
        )
        assert remaining == {
            horizon_start: 3,
            horizon_start + timedelta(days=1): 3,
        }

    def test_uninitialized_dates_are_absent_not_infinite(
        self, tenant, property, room_type, horizon_start
    ):
        dr = DateRange(horizon_start, horizon_start + timedelta(days=1))
        remaining = AvailabilityQuery.remaining_for_range(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
        )
        assert remaining == {}

    def test_is_sellable_true_when_every_night_has_enough(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=2,
            start_date=horizon_start,
            horizon_days=3,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=2))
        assert AvailabilityQuery.is_sellable(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=2,
        )
        assert not AvailabilityQuery.is_sellable(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=3,
        )

    def test_is_sellable_false_when_any_night_is_uninitialized(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=1,  # only 1 night open
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=2))  # asks for 2
        assert not AvailabilityQuery.is_sellable(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=1,
        )


@pytest.mark.django_db
class TestInventoryServiceSell:
    def test_sell_increments_sold_across_the_whole_window(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=3,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=3))
        InventoryService.sell(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=2,
            idempotency_key="sell-1",
        )
        rows = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
        ).order_by("business_date")
        assert [r.sold for r in rows] == [2, 2, 2]
        assert [r.remaining for r in rows] == [3, 3, 3]

    def test_sell_is_all_or_nothing_across_a_multi_night_window(
        self, tenant, property, room_type, horizon_start
    ):
        """One night has less capacity than the rest — the whole 3-night
        request must fail, and NONE of the nights show any consumption."""
        AvailabilitySlot.objects.bulk_create(
            [
                AvailabilitySlot(
                    id=100 + i,
                    tenant_id=tenant.id,
                    property_id=property.id,
                    room_type_id=room_type.id,
                    channel=Channel.DIRECT,
                    business_date=horizon_start + timedelta(days=i),
                    total_units=total,
                )
                for i, total in enumerate([5, 5, 1])  # day 2 only has 1 unit
            ]
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=3))
        with pytest.raises(InsufficientAvailability):
            InventoryService.sell(
                tenant_id=tenant.id,
                property_id=property.id,
                room_type_id=room_type.id,
                date_range=dr,
                quantity=2,
                idempotency_key="sell-partial",
            )
        rows = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
        ).order_by("business_date")
        assert [r.sold for r in rows] == [0, 0, 0]  # no partial consumption

    def test_sell_raises_for_an_uninitialized_night_in_the_window(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=1,  # only day 0
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=2))  # asks for day 0+1
        with pytest.raises(InsufficientAvailability):
            InventoryService.sell(
                tenant_id=tenant.id,
                property_id=property.id,
                room_type_id=room_type.id,
                date_range=dr,
                quantity=1,
                idempotency_key="sell-missing",
            )

    def test_sell_is_idempotent_per_key_no_double_consumption(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=1,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=1))
        InventoryService.sell(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=2,
            idempotency_key="same-key",
        )
        InventoryService.sell(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=2,
            idempotency_key="same-key",
        )
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
        )
        assert slot.sold == 2  # NOT 4 — the replay returned the stored result


@pytest.mark.django_db
class TestInventoryServiceHoldAndConvert:
    def test_hold_then_convert_hold_to_sold(self, tenant, property, room_type, horizon_start):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=2,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=2))
        InventoryService.hold(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=2,
            idempotency_key="hold-1",
        )
        rows = list(
            AvailabilitySlot.objects.filter(
                tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
            ).order_by("business_date")
        )
        assert [r.reserved for r in rows] == [2, 2]
        assert [r.sold for r in rows] == [0, 0]

        InventoryService.convert_hold_to_sold(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=2,
            idempotency_key="convert-1",
        )
        rows = list(
            AvailabilitySlot.objects.filter(
                tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
            ).order_by("business_date")
        )
        assert [r.reserved for r in rows] == [0, 0]
        assert [r.sold for r in rows] == [2, 2]

    def test_convert_hold_to_sold_raises_when_not_enough_was_held(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=1,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=1))
        InventoryService.hold(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=1,
            idempotency_key="hold-2",
        )
        with pytest.raises(InsufficientAvailability):
            InventoryService.convert_hold_to_sold(
                tenant_id=tenant.id,
                property_id=property.id,
                room_type_id=room_type.id,
                date_range=dr,
                quantity=2,
                idempotency_key="convert-2",
            )


@pytest.mark.django_db
class TestInventoryServiceRelease:
    def test_release_sold_decrements_and_reopens_capacity(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=1,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=1))
        InventoryService.sell(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=3,
            idempotency_key="rel-sell-1",
        )
        InventoryService.release_sold(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=2,
        )
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
        )
        assert slot.sold == 1
        assert slot.remaining == 4

    def test_release_is_idempotent_never_goes_negative(
        self, tenant, property, room_type, horizon_start
    ):
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            total_units=5,
            start_date=horizon_start,
            horizon_days=1,
        )
        dr = DateRange(horizon_start, horizon_start + timedelta(days=1))
        InventoryService.sell(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=1,
            idempotency_key="rel-sell-2",
        )
        InventoryService.release_sold(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=1,
        )
        # Releasing again (nothing left to release) must be a safe no-op.
        InventoryService.release_sold(
            tenant_id=tenant.id,
            property_id=property.id,
            room_type_id=room_type.id,
            date_range=dr,
            quantity=5,
        )
        slot = AvailabilitySlot.objects.get(
            tenant_id=tenant.id, property_id=property.id, room_type_id=room_type.id
        )
        assert slot.sold == 0
        assert slot.remaining == 5
