"""PricingService.price() / PriceSimulationService computation tests (M6)."""
from datetime import date

import pytest

from apps.policies.models import PolicyType
from apps.policies.services import PolicyService
from apps.pricing.models import AdjustmentType, ModifierType
from apps.pricing.services import (
    NoRatePlanFound,
    PriceSimulationService,
    PricingService,
    RatePlanNotActive,
)
from apps.shared.models import OutboxEvent
from apps.shared.value_objects import Currency, GuestCount, Money, StayPeriod

USD = Currency.USD


def _stay(arrival, nights):
    from datetime import timedelta

    return StayPeriod(arrival=arrival, departure=arrival + timedelta(days=nights))


ONE_ADULT = GuestCount(adults=1, children=0)


@pytest.mark.django_db
class TestPriceComputationBasic:
    def test_base_only_price(self, property, room_type, rate_plan):
        stay = _stay(date(2026, 3, 1), 2)  # Sun, Mon — no modifiers configured

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert breakdown.total == Money(20000, USD)
        assert breakdown.subtotal == breakdown.total
        assert len(breakdown.nightly) == 2

    def test_no_rate_plan_raises(self, property, room_type):
        stay = _stay(date(2026, 3, 1), 1)

        with pytest.raises(NoRatePlanFound):
            PricingService.price(property, room_type, stay, ONE_ADULT)

    def test_retired_plan_not_found_by_active_lookup(self, property, room_type, rate_plan):
        # price() resolves via the active-plan lookup, so a retired plan is
        # invisible to it (NoRatePlanFound), not caught by the status guard.
        PricingService.retire_rate_plan(rate_plan)
        stay = _stay(date(2026, 3, 1), 1)

        with pytest.raises(NoRatePlanFound):
            PricingService.price(property, room_type, stay, ONE_ADULT)

    def test_retired_plan_rejected_by_simulation(self, rate_plan):
        # PriceSimulationService takes an explicit rate_plan, bypassing the
        # active-lookup — this is where RatePlanNotActive is actually raised.
        PricingService.retire_rate_plan(rate_plan)
        stay = _stay(date(2026, 3, 1), 1)

        with pytest.raises(RatePlanNotActive):
            PriceSimulationService.simulate(rate_plan, stay, ONE_ADULT)

    def test_draft_plan_not_found_by_active_lookup(self, tenant, property, room_type):
        PricingService.create_rate_plan(
            tenant=tenant, property=property, room_type=room_type, code="DRAFT-1",
            base_rate_minor_units=5000, currency=property.currency,
        )
        stay = _stay(date(2026, 3, 1), 1)

        with pytest.raises(NoRatePlanFound):
            PricingService.price(property, room_type, stay, ONE_ADULT)


@pytest.mark.django_db
class TestOverrideApplication:
    def test_absolute_override_applies_only_to_covered_nights(self, property, room_type, rate_plan):
        PricingService.add_override(
            rate_plan, date(2026, 3, 2), date(2026, 3, 2), AdjustmentType.ABSOLUTE, 5000
        )
        stay = _stay(date(2026, 3, 1), 3)  # Mar 1, 2, 3

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        by_night = {n.night: n for n in breakdown.nightly}
        assert by_night[date(2026, 3, 1)].total == Money(10000, USD)  # untouched
        assert by_night[date(2026, 3, 2)].total == Money(15000, USD)  # 10000 + 5000
        assert by_night[date(2026, 3, 3)].total == Money(10000, USD)  # untouched

    def test_percent_override_applies_to_base(self, property, room_type, rate_plan):
        PricingService.add_override(
            rate_plan, date(2026, 3, 2), date(2026, 3, 2), AdjustmentType.PERCENT, 20
        )
        stay = _stay(date(2026, 3, 2), 1)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert breakdown.total == Money(12000, USD)  # 10000 + 20% of 10000


@pytest.mark.django_db
class TestCalendarModifiers:
    def test_season_modifier_matches_inclusive_range(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.SEASON,
            {"start_date": "2026-12-20", "end_date": "2026-12-26", "adjustment_pct": 10},
        )
        stay = _stay(date(2026, 12, 25), 2)  # Dec 25 (in season), Dec 26 (last day, in season)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert all(len(n.adjustments) == 1 for n in breakdown.nightly)
        assert breakdown.total == Money(22000, USD)  # 2 x (10000 + 1000)

    def test_season_modifier_does_not_match_outside_range(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.SEASON,
            {"start_date": "2026-12-20", "end_date": "2026-12-26", "adjustment_pct": 10},
        )
        stay = _stay(date(2026, 3, 1), 1)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert breakdown.nightly[0].adjustments == ()
        assert breakdown.total == Money(10000, USD)

    def test_weekend_modifier_iso_weekday_saturday_sunday(self, property, room_type, rate_plan):
        # 2026-03-01 is a Sunday (ISO weekday 7); 2026-03-02 is Monday (1).
        PricingService.add_modifier(
            rate_plan, ModifierType.WEEKEND, {"weekdays": [6, 7], "adjustment_pct": 50}
        )
        stay = _stay(date(2026, 3, 1), 2)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        by_night = {n.night: n for n in breakdown.nightly}
        assert by_night[date(2026, 3, 1)].total == Money(15000, USD)  # Sunday: +50%
        assert by_night[date(2026, 3, 2)].total == Money(10000, USD)  # Monday: untouched

    def test_holiday_modifier_matches_exact_date(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.HOLIDAY,
            {"dates": ["2026-12-25"], "adjustment_pct": 30},
        )
        stay = _stay(date(2026, 12, 24), 2)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        by_night = {n.night: n for n in breakdown.nightly}
        assert by_night[date(2026, 12, 24)].total == Money(10000, USD)
        assert by_night[date(2026, 12, 25)].total == Money(13000, USD)


@pytest.mark.django_db
class TestSegmentModifiers:
    def test_long_stay_applies_once_to_stay_not_per_night(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.LONG_STAY, {"min_nights": 3, "adjustment_pct": -10}
        )
        # Mixed nights: no per-night factors, just proves the discount is one
        # stay-level line item on the summed subtotal, not applied 3 times.
        stay = _stay(date(2026, 3, 1), 3)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert len(breakdown.stay_adjustments) == 1
        assert breakdown.stay_adjustments[0].amount == Money(-3000, USD)  # -10% of 30000
        assert breakdown.total == Money(27000, USD)
        # Nightly entries carry no long_stay adjustment themselves.
        assert all(n.adjustments == () for n in breakdown.nightly)

    def test_long_stay_does_not_apply_below_threshold(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.LONG_STAY, {"min_nights": 7, "adjustment_pct": -10}
        )
        stay = _stay(date(2026, 3, 1), 2)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert breakdown.stay_adjustments == ()

    def test_corporate_requires_explicit_flag(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.CORPORATE, {"adjustment_pct": -15}
        )
        stay = _stay(date(2026, 3, 1), 1)

        without_flag = PricingService.price(property, room_type, stay, ONE_ADULT)
        with_flag = PricingService.price(
            property, room_type, stay, ONE_ADULT, is_corporate=True
        )

        assert without_flag.stay_adjustments == ()
        assert with_flag.total == Money(8500, USD)  # 10000 - 15%

    def test_mixed_nightly_and_segment_modifiers_combine_correctly(
        self, property, room_type, rate_plan
    ):
        """Proves stay-level clamping/adjustments are independent of per-night
        (mixed) factors: a weekend surcharge on one night plus a long-stay
        discount on the whole stay must both land in the same breakdown."""
        PricingService.add_modifier(
            rate_plan, ModifierType.WEEKEND, {"weekdays": [7], "adjustment_pct": 50}
        )
        PricingService.add_modifier(
            rate_plan, ModifierType.LONG_STAY, {"min_nights": 2, "adjustment_pct": -10}
        )
        stay = _stay(date(2026, 3, 1), 2)  # Sunday + Monday

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        nightly_subtotal = Money(15000, USD) + Money(10000, USD)  # 25000
        expected_subtotal = nightly_subtotal + nightly_subtotal.percentage_of(-10)
        assert breakdown.subtotal == expected_subtotal  # includes the stay-level discount
        assert breakdown.total == expected_subtotal  # no policy configured, so unclamped


@pytest.mark.django_db
class TestPolicyFloorCeiling:
    def _publish_pricing_policy(self, tenant, rules, effective_from=date(2020, 1, 1)):
        draft = PolicyService.create_draft(
            tenant=tenant, policy_type=PolicyType.PRICING, rules=rules,
            effective_from=effective_from,
        )
        return PolicyService.publish(draft.id)

    def test_no_policy_configured_is_unclamped(self, property, room_type, rate_plan):
        stay = _stay(date(2026, 3, 1), 1)

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert breakdown.floor_minor_units is None
        assert breakdown.ceiling_minor_units is None
        assert breakdown.was_clamped is False

    def test_ceiling_clamps_stay_total(self, tenant, property, room_type, rate_plan):
        self._publish_pricing_policy(tenant, {"ceiling_minor_units": 15000})
        stay = _stay(date(2026, 3, 1), 3)  # subtotal 30000, way over the ceiling

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert breakdown.total == Money(15000, USD)
        assert breakdown.subtotal == Money(30000, USD)
        assert breakdown.was_clamped is True

    def test_floor_clamps_stay_total(self, tenant, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.LONG_STAY, {"min_nights": 1, "adjustment_pct": -90}
        )
        self._publish_pricing_policy(tenant, {"floor_minor_units": 8000})
        stay = _stay(date(2026, 3, 1), 1)  # 10000 - 90% = 1000, below the floor

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert breakdown.total == Money(8000, USD)
        assert breakdown.was_clamped is True

    def test_clamp_is_stay_level_not_per_night(self, tenant, property, room_type, rate_plan):
        """A ceiling below a single night's rate must still clamp the SUM,
        not truncate each night individually — proves stay-level semantics."""
        self._publish_pricing_policy(tenant, {"ceiling_minor_units": 12000})
        stay = _stay(date(2026, 3, 1), 3)  # 3 x 10000 = 30000 subtotal

        breakdown = PricingService.price(property, room_type, stay, ONE_ADULT)

        # Each individual NightlyPrice is untouched (10000) — only the total is clamped.
        assert all(n.total == Money(10000, USD) for n in breakdown.nightly)
        assert breakdown.total == Money(12000, USD)


@pytest.mark.django_db
class TestDeterminism:
    def test_identical_inputs_produce_identical_breakdown(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.WEEKEND, {"weekdays": [6, 7], "adjustment_pct": 20}
        )
        stay = _stay(date(2026, 3, 1), 3)

        first = PricingService.price(property, room_type, stay, ONE_ADULT)
        second = PricingService.price(property, room_type, stay, ONE_ADULT)

        assert first == second
        assert first.to_dict() == second.to_dict()


@pytest.mark.django_db
class TestPriceSimulationService:
    def test_matches_pricing_service_for_identical_inputs(self, property, room_type, rate_plan):
        PricingService.add_modifier(
            rate_plan, ModifierType.WEEKEND, {"weekdays": [6, 7], "adjustment_pct": 20}
        )
        stay = _stay(date(2026, 3, 1), 2)

        priced = PricingService.price(property, room_type, stay, ONE_ADULT)
        simulated = PriceSimulationService.simulate(rate_plan, stay, ONE_ADULT)

        assert priced == simulated

    def test_writes_nothing(self, property, room_type, rate_plan):
        stay = _stay(date(2026, 3, 1), 1)
        events_before = OutboxEvent.objects.count()
        plans_before = rate_plan.__class__.objects.count()

        PriceSimulationService.simulate(rate_plan, stay, ONE_ADULT)

        assert OutboxEvent.objects.count() == events_before
        assert rate_plan.__class__.objects.count() == plans_before
