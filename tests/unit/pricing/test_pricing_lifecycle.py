"""Rate plan / override / modifier lifecycle tests (M6)."""
from datetime import date

import pytest
from django.db import IntegrityError

from apps.pricing.models import (
    AdjustmentType,
    ModifierType,
    RateModifier,
    RateOverride,
    RatePlan,
    RatePlanStatus,
)
from apps.pricing.services import (
    InvalidModifierConfig,
    OverlappingRateOverride,
    PricingService,
    RatePlanCurrencyMismatch,
)
from apps.shared.exceptions import ConcurrencyError
from apps.shared.models import OutboxEvent


@pytest.mark.django_db
class TestRatePlanLifecycle:
    def test_create_draft_rate_plan(self, tenant, property, room_type):
        plan = PricingService.create_rate_plan(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code="STD-RACK",
            base_rate_minor_units=10000,
            currency=property.currency,
        )

        assert plan.status == RatePlanStatus.DRAFT
        assert plan.currency == property.currency

    def test_create_rejects_currency_mismatch(self, tenant, property, room_type):
        with pytest.raises(RatePlanCurrencyMismatch):
            PricingService.create_rate_plan(
                tenant=tenant,
                property=property,
                room_type=room_type,
                code="STD-RACK",
                base_rate_minor_units=10000,
                currency="NGN",  # property.currency is USD
            )

    def test_activate_rate_plan(self, rate_plan):
        assert rate_plan.status == RatePlanStatus.ACTIVE

    def test_retire_rate_plan(self, rate_plan):
        retired = PricingService.retire_rate_plan(rate_plan)

        assert retired.status == RatePlanStatus.RETIRED

    def test_optimistic_locking_detects_concurrent_edit(self, rate_plan):
        stale = RatePlan.objects.get(id=rate_plan.id)
        fresh = RatePlan.objects.get(id=rate_plan.id)

        fresh.sellable = False
        fresh.save()

        with pytest.raises(ConcurrencyError):
            stale.sellable = True
            stale.save()

    def test_activate_emits_rate_changed_event(self, tenant, property, room_type):
        plan = PricingService.create_rate_plan(
            tenant=tenant, property=property, room_type=room_type, code="EVT-1",
            base_rate_minor_units=5000, currency=property.currency,
        )

        PricingService.activate_rate_plan(plan)

        assert OutboxEvent.objects.filter(
            event_type="rate.changed", tenant_id=tenant.id, aggregate_id=str(plan.id)
        ).exists()


@pytest.mark.django_db
class TestRateOverride:
    def test_add_absolute_override(self, rate_plan):
        override = PricingService.add_override(
            rate_plan, date(2026, 12, 24), date(2026, 12, 26), AdjustmentType.ABSOLUTE, 5000
        )

        assert override.adjustment_type == AdjustmentType.ABSOLUTE
        assert override.adjustment_minor_units == 5000

    def test_add_percent_override(self, rate_plan):
        override = PricingService.add_override(
            rate_plan, date(2026, 12, 24), date(2026, 12, 26), AdjustmentType.PERCENT, 20
        )

        assert override.adjustment_type == AdjustmentType.PERCENT

    def test_overlapping_inclusive_ranges_rejected(self, rate_plan):
        PricingService.add_override(
            rate_plan, date(2026, 12, 20), date(2026, 12, 26), AdjustmentType.PERCENT, 10
        )

        with pytest.raises(OverlappingRateOverride):
            PricingService.add_override(
                # shares Dec 26 with the existing [20,26] range — inclusive overlap
                rate_plan, date(2026, 12, 26), date(2026, 12, 31), AdjustmentType.PERCENT, 10
            )

    def test_adjacent_non_overlapping_ranges_are_accepted(self, rate_plan):
        PricingService.add_override(
            rate_plan, date(2026, 12, 20), date(2026, 12, 25), AdjustmentType.PERCENT, 10
        )

        # Dec 26 is the day AFTER Dec 25 — no shared day under inclusive semantics.
        second = PricingService.add_override(
            rate_plan, date(2026, 12, 26), date(2026, 12, 31), AdjustmentType.PERCENT, 10
        )

        assert second.start_date == date(2026, 12, 26)

    def test_overlap_check_ignores_inactive_overrides(self, rate_plan):
        first = PricingService.add_override(
            rate_plan, date(2026, 12, 20), date(2026, 12, 26), AdjustmentType.PERCENT, 10
        )
        first.active = False
        first.save()

        # Now allowed — the only prior override covering this range is inactive.
        second = PricingService.add_override(
            rate_plan, date(2026, 12, 20), date(2026, 12, 26), AdjustmentType.PERCENT, 15
        )
        assert second.active is True

    def test_add_override_emits_rate_changed_event(self, tenant, rate_plan):
        PricingService.add_override(
            rate_plan, date(2026, 12, 24), date(2026, 12, 26), AdjustmentType.ABSOLUTE, 5000
        )

        assert OutboxEvent.objects.filter(
            event_type="rate.changed", tenant_id=tenant.id, aggregate_id=str(rate_plan.id)
        ).count() >= 1

    def test_rejects_zero_adjustment_at_db_level(self, rate_plan):
        with pytest.raises(IntegrityError):
            RateOverride.objects.create(
                tenant=rate_plan.tenant,
                rate_plan=rate_plan,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 2),
                adjustment_type=AdjustmentType.PERCENT,
                adjustment_minor_units=0,
            )


@pytest.mark.django_db
class TestRateModifier:
    def test_season_modifier_valid_config(self, rate_plan):
        modifier = PricingService.add_modifier(
            rate_plan, ModifierType.SEASON,
            {"start_date": "2026-12-01", "end_date": "2026-12-31", "adjustment_pct": 20},
        )
        assert modifier.modifier_type == ModifierType.SEASON

    def test_season_modifier_end_before_start_rejected(self, rate_plan):
        with pytest.raises(InvalidModifierConfig):
            PricingService.add_modifier(
                rate_plan, ModifierType.SEASON,
                {"start_date": "2026-12-31", "end_date": "2026-12-01", "adjustment_pct": 20},
            )

    def test_weekend_modifier_valid_config(self, rate_plan):
        modifier = PricingService.add_modifier(
            rate_plan, ModifierType.WEEKEND, {"weekdays": [6, 7], "adjustment_pct": 15}
        )
        assert modifier.config["weekdays"] == [6, 7]

    @pytest.mark.parametrize("bad_weekday", [0, 8, -1, 100])
    def test_weekend_modifier_rejects_out_of_range_weekday(self, rate_plan, bad_weekday):
        with pytest.raises(InvalidModifierConfig):
            PricingService.add_modifier(
                rate_plan, ModifierType.WEEKEND,
                {"weekdays": [bad_weekday], "adjustment_pct": 15},
            )

    @pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5, 6, 7])
    def test_weekend_modifier_accepts_every_iso_weekday(self, rate_plan, weekday):
        modifier = PricingService.add_modifier(
            rate_plan, ModifierType.WEEKEND, {"weekdays": [weekday], "adjustment_pct": 15}
        )
        assert weekday in modifier.config["weekdays"]

    def test_holiday_modifier_valid_config(self, rate_plan):
        modifier = PricingService.add_modifier(
            rate_plan, ModifierType.HOLIDAY,
            {"dates": ["2026-12-25"], "adjustment_pct": 25},
        )
        assert modifier.config["dates"] == ["2026-12-25"]

    def test_holiday_modifier_rejects_invalid_date(self, rate_plan):
        with pytest.raises(InvalidModifierConfig):
            PricingService.add_modifier(
                rate_plan, ModifierType.HOLIDAY,
                {"dates": ["not-a-date"], "adjustment_pct": 25},
            )

    def test_long_stay_modifier_valid_config(self, rate_plan):
        modifier = PricingService.add_modifier(
            rate_plan, ModifierType.LONG_STAY, {"min_nights": 7, "adjustment_pct": -10}
        )
        assert modifier.config["min_nights"] == 7

    def test_long_stay_modifier_rejects_non_positive_min_nights(self, rate_plan):
        with pytest.raises(InvalidModifierConfig):
            PricingService.add_modifier(
                rate_plan, ModifierType.LONG_STAY, {"min_nights": 0, "adjustment_pct": -10}
            )

    def test_corporate_modifier_valid_config(self, rate_plan):
        modifier = PricingService.add_modifier(
            rate_plan, ModifierType.CORPORATE, {"adjustment_pct": -15}
        )
        assert modifier.config["adjustment_pct"] == -15

    def test_missing_adjustment_pct_rejected(self, rate_plan):
        with pytest.raises(InvalidModifierConfig):
            PricingService.add_modifier(rate_plan, ModifierType.CORPORATE, {})

    def test_rejects_invalid_modifier_type_at_db_level(self, rate_plan):
        with pytest.raises(IntegrityError):
            RateModifier.objects.create(
                tenant=rate_plan.tenant,
                rate_plan=rate_plan,
                modifier_type="not-a-type",
                config={},
            )


@pytest.mark.django_db
class TestTenantIsolation:
    def test_rate_plans_scoped_per_tenant(self, tenant, tenant2, property, room_type):
        from apps.properties.models import Property
        from apps.rooms.models import RoomType as RoomTypeModel

        property2 = Property.objects.create(
            tenant=tenant2, code="P2", name="Globex Hotel", status=Property.Status.ACTIVE,
            currency="NGN", timezone="UTC", check_in_time="14:00:00", check_out_time="12:00:00",
        )
        room_type2 = RoomTypeModel.objects.create(
            tenant=tenant2, code="STD-KING", name="Standard King",
            status=RoomTypeModel.Status.ACTIVE, max_occupancy=2,
        )

        PricingService.create_rate_plan(
            tenant=tenant, property=property, room_type=room_type, code="SAME-CODE",
            base_rate_minor_units=10000, currency=property.currency,
        )
        PricingService.create_rate_plan(
            tenant=tenant2, property=property2, room_type=room_type2, code="SAME-CODE",
            base_rate_minor_units=8000, currency=property2.currency,
        )

        assert RatePlan.objects.filter(tenant=tenant).count() == 1
        assert RatePlan.objects.filter(tenant=tenant2).count() == 1
