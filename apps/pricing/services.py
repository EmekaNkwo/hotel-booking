"""Pricing Engine — the only place price is computed (M6, DR-06).

Authoritative references:
- SDD S11.3 — Pricing Engine ("how much, and why?")
- DDS S8 — Pricing
- Implementation roadmap M6

Modifier config contract (fixed shapes, no generic interpreter — R3 "data,
not hardcoded branches" means the *values* are data; the five evaluators
below are the only code that reads them):

- ``season``:    {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "adjustment_pct": int}
                 Matches a night when start_date <= night <= end_date (inclusive).
- ``weekend``:   {"weekdays": [1..7, ...], "adjustment_pct": int}
                 ISO weekday numbering: 1=Monday .. 7=Sunday. Matches a night
                 when ``night.isoweekday()`` is in the list.
- ``holiday``:   {"dates": ["YYYY-MM-DD", ...], "adjustment_pct": int}
                 Matches a night when its date is in the list.
- ``long_stay``: {"min_nights": int, "adjustment_pct": int}
                 Stay-level: matches when ``stay_period.nights >= min_nights``.
- ``corporate``: {"adjustment_pct": int}
                 Stay-level: matches when the caller passes ``is_corporate=True``.

Every adjustment (override or modifier) is computed against a fixed base —
the rate plan's ``base_rate_minor_units`` for calendar modifiers/overrides,
the summed nightly subtotal for segment modifiers — and summed as line
items. Adjustments never compound on each other (no order-dependent
multiplication), so the breakdown is a flat, auditable list of percentages
of a known base, not a chain of running totals.
"""

from datetime import date, timedelta

from django.db import transaction

from apps.policies.services import NoPolicyFound, PolicyService
from apps.pricing.models import (
    AdjustmentType,
    ModifierType,
    RateModifier,
    RateOverride,
    RatePlan,
    RatePlanStatus,
)
from apps.shared.services.outbox import OutboxService
from apps.shared.value_objects import Currency, LineItem, Money, NightlyPrice, PriceBreakdown

_CALENDAR_TYPES = (ModifierType.SEASON, ModifierType.WEEKEND, ModifierType.HOLIDAY)
_SEGMENT_TYPES = (ModifierType.LONG_STAY, ModifierType.CORPORATE)


class RatePlanCurrencyMismatch(Exception):
    """Raised when a rate plan's currency does not equal its property's currency."""


class RatePlanNotActive(Exception):
    """Raised when price() is asked to price a non-active (draft/retired) plan."""


class NoRatePlanFound(Exception):
    """Raised when no active, sellable rate plan matches (property, room_type)."""


class OverlappingRateOverride(Exception):
    """Raised when a new override's inclusive date range overlaps an active one."""


class InvalidModifierConfig(Exception):
    """Raised when a modifier's config does not match its type's fixed shape."""


class InvalidPricingPolicy(Exception):
    """Raised when PolicyService.pricing_policy() returns a malformed
    floor_minor_units/ceiling_minor_units contract."""


# ---------------------------------------------------------------------------
# Modifier config validation — one function per fixed shape, no interpreter.
# ---------------------------------------------------------------------------

def _require_int(config: dict, key: str, modifier_type: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidModifierConfig(f"{modifier_type} config.{key} must be an int, got {value!r}.")
    return value


def _require_date(config: dict, key: str, modifier_type: str) -> date:
    value = config.get(key)
    if not isinstance(value, str):
        raise InvalidModifierConfig(f"{modifier_type} config.{key} must be an ISO date string.")
    try:
        return date.fromisoformat(value)
    except ValueError as err:
        raise InvalidModifierConfig(
            f"{modifier_type} config.{key} is not a valid ISO date: {value!r}."
        ) from err


def validate_modifier_config(modifier_type: str, config: dict) -> None:
    """Raises InvalidModifierConfig if config does not match modifier_type's fixed shape."""
    if not isinstance(config, dict):
        raise InvalidModifierConfig(f"{modifier_type} config must be a dict, got {config!r}.")

    if modifier_type == ModifierType.SEASON:
        start = _require_date(config, "start_date", modifier_type)
        end = _require_date(config, "end_date", modifier_type)
        if end < start:
            raise InvalidModifierConfig("season config.end_date must be on/after start_date.")
        _require_int(config, "adjustment_pct", modifier_type)

    elif modifier_type == ModifierType.WEEKEND:
        weekdays = config.get("weekdays")
        if not isinstance(weekdays, list) or not weekdays:
            raise InvalidModifierConfig("weekend config.weekdays must be a non-empty list.")
        for day in weekdays:
            if not isinstance(day, int) or isinstance(day, bool) or not (1 <= day <= 7):
                raise InvalidModifierConfig(
                    f"weekend config.weekdays entries must be ISO weekdays 1..7, got {day!r}."
                )
        _require_int(config, "adjustment_pct", modifier_type)

    elif modifier_type == ModifierType.HOLIDAY:
        dates = config.get("dates")
        if not isinstance(dates, list) or not dates:
            raise InvalidModifierConfig("holiday config.dates must be a non-empty list.")
        for raw in dates:
            if not isinstance(raw, str):
                raise InvalidModifierConfig(
                    f"holiday config.dates entries must be strings, got {raw!r}."
                )
            try:
                date.fromisoformat(raw)
            except ValueError as err:
                raise InvalidModifierConfig(
                    f"holiday config.dates entry is not a valid ISO date: {raw!r}."
                ) from err
        _require_int(config, "adjustment_pct", modifier_type)

    elif modifier_type == ModifierType.LONG_STAY:
        min_nights = _require_int(config, "min_nights", modifier_type)
        if min_nights <= 0:
            raise InvalidModifierConfig("long_stay config.min_nights must be positive.")
        _require_int(config, "adjustment_pct", modifier_type)

    elif modifier_type == ModifierType.CORPORATE:
        _require_int(config, "adjustment_pct", modifier_type)

    else:
        raise InvalidModifierConfig(f"Unknown modifier_type: {modifier_type!r}.")


def _calendar_modifier_matches(modifier: RateModifier, night: date) -> bool:
    config = modifier.config
    if modifier.modifier_type == ModifierType.SEASON:
        start = date.fromisoformat(config["start_date"])
        end = date.fromisoformat(config["end_date"])
        return start <= night <= end
    if modifier.modifier_type == ModifierType.WEEKEND:
        return night.isoweekday() in config["weekdays"]
    if modifier.modifier_type == ModifierType.HOLIDAY:
        return night.isoformat() in config["dates"]
    return False


def _segment_modifier_matches(modifier: RateModifier, nights: int, is_corporate: bool) -> bool:
    config = modifier.config
    if modifier.modifier_type == ModifierType.LONG_STAY:
        return nights >= config["min_nights"]
    if modifier.modifier_type == ModifierType.CORPORATE:
        return is_corporate
    return False


def _override_covering(overrides: list[RateOverride], night: date) -> RateOverride | None:
    for override in overrides:
        if override.start_date <= night <= override.end_date:
            return override
    return None


def _override_adjustment(override: RateOverride, base: Money) -> Money:
    if override.adjustment_type == AdjustmentType.ABSOLUTE:
        return Money(override.adjustment_minor_units, base.currency)
    # PERCENT: adjustment_minor_units is reinterpreted as a raw percentage,
    # not literal minor units (RateOverride has one shared numeric column
    # for both adjustment types — see apps.pricing.models.RateOverride).
    return base.percentage_of(override.adjustment_minor_units)


def _overrides_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Inclusive-range overlap: [a_start, a_end] and [b_start, b_end]."""
    return a_start <= b_end and a_end >= b_start


class RateQuery:
    """Read-model selector — the mirror of PricingService."""

    @staticmethod
    def active_plan(property, room_type) -> RatePlan | None:
        return RatePlan.objects.filter(
            property=property,
            room_type=room_type,
            status=RatePlanStatus.ACTIVE,
            sellable=True,
        ).first()

    @staticmethod
    def effective_overrides(rate_plan: RatePlan):
        return RateOverride.objects.filter(rate_plan=rate_plan, active=True).order_by("start_date")

    @staticmethod
    def active_modifiers(rate_plan: RatePlan, modifier_type: str | None = None):
        qs = RateModifier.objects.filter(rate_plan=rate_plan, active=True)
        if modifier_type is not None:
            qs = qs.filter(modifier_type=modifier_type)
        return qs


class PricingService:
    """Rate plan lifecycle + the price computation (DR-06)."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def create_rate_plan(
        tenant, property, room_type, code: str, base_rate_minor_units: int, currency: str,
        policy_refs: dict | None = None,
    ) -> RatePlan:
        if currency != property.currency:
            raise RatePlanCurrencyMismatch(
                f"RatePlan currency {currency!r} must equal property currency "
                f"{property.currency!r}; multi-currency properties are not supported."
            )
        plan = RatePlan(
            tenant=tenant,
            property=property,
            room_type=room_type,
            code=code,
            base_rate_minor_units=base_rate_minor_units,
            currency=currency,
            status=RatePlanStatus.DRAFT,
            policy_refs=policy_refs or {},
        )
        plan.full_clean()
        plan.save()
        return plan

    @staticmethod
    def activate_rate_plan(rate_plan: RatePlan) -> RatePlan:
        with transaction.atomic():
            rate_plan.status = RatePlanStatus.ACTIVE
            rate_plan.save()
            PricingService._emit_rate_changed(rate_plan)
            return rate_plan

    @staticmethod
    def retire_rate_plan(rate_plan: RatePlan) -> RatePlan:
        with transaction.atomic():
            rate_plan.status = RatePlanStatus.RETIRED
            rate_plan.save()
            PricingService._emit_rate_changed(rate_plan)
            return rate_plan

    @staticmethod
    def add_override(
        rate_plan: RatePlan, start_date: date, end_date: date, adjustment_type: str,
        adjustment_minor_units: int,
    ) -> RateOverride:
        for existing in RateQuery.effective_overrides(rate_plan):
            if _overrides_overlap(start_date, end_date, existing.start_date, existing.end_date):
                raise OverlappingRateOverride(
                    f"Override [{start_date}, {end_date}] overlaps existing active "
                    f"override [{existing.start_date}, {existing.end_date}] on the same plan."
                )
        with transaction.atomic():
            override = RateOverride(
                tenant=rate_plan.tenant,
                rate_plan=rate_plan,
                start_date=start_date,
                end_date=end_date,
                adjustment_type=adjustment_type,
                adjustment_minor_units=adjustment_minor_units,
            )
            override.full_clean()
            override.save()
            PricingService._emit_rate_changed(rate_plan)
            return override

    @staticmethod
    def add_modifier(rate_plan: RatePlan, modifier_type: str, config: dict) -> RateModifier:
        validate_modifier_config(modifier_type, config)
        with transaction.atomic():
            modifier = RateModifier(
                tenant=rate_plan.tenant,
                rate_plan=rate_plan,
                modifier_type=modifier_type,
                config=config,
            )
            modifier.full_clean()
            modifier.save()
            PricingService._emit_rate_changed(rate_plan)
            return modifier

    @staticmethod
    def _emit_rate_changed(rate_plan: RatePlan) -> None:
        OutboxService.record_event(
            event_type="rate.changed",
            tenant_id=rate_plan.tenant_id,
            payload={
                "rate_plan_id": rate_plan.id,
                "room_type_id": rate_plan.room_type_id,
                "currency": rate_plan.currency,
            },
            aggregate_type="rateplan",
            aggregate_id=str(rate_plan.id),
        )

    # ------------------------------------------------------------------
    # Computation — the only place price is computed (DR-06)
    # ------------------------------------------------------------------

    @staticmethod
    def price(
        property, room_type, stay_period, guest_count, *, is_corporate: bool = False
    ) -> PriceBreakdown:
        """Resolve the active rate plan and compute a PriceBreakdown.

        ``guest_count`` is accepted per the roadmap signature but no v1 rule
        prices by occupancy yet — it is not read by this computation.
        """
        rate_plan = RateQuery.active_plan(property, room_type)
        if rate_plan is None:
            raise NoRatePlanFound(
                f"No active, sellable rate plan for property {property.id}, "
                f"room_type {room_type.id}."
            )
        return _compute(rate_plan, stay_period, is_corporate=is_corporate)


class PriceSimulationService:
    """What-if pricing for staff (v2 preview) — never persists, never emits events."""

    @staticmethod
    def simulate(
        rate_plan: RatePlan, stay_period, guest_count, *, is_corporate: bool = False
    ) -> PriceBreakdown:
        """Same computation as PricingService.price(), given an explicit rate
        plan (no resolution, no lookup side effects) — purely a read."""
        return _compute(rate_plan, stay_period, is_corporate=is_corporate)


def _compute(rate_plan: RatePlan, stay_period, *, is_corporate: bool) -> PriceBreakdown:
    if rate_plan.status != RatePlanStatus.ACTIVE:
        raise RatePlanNotActive(
            f"Cannot price rate plan {rate_plan.id} in status {rate_plan.status!r}; "
            "only active plans can be priced."
        )

    currency = Currency(rate_plan.currency)
    base = Money(rate_plan.base_rate_minor_units, currency)
    overrides = list(RateQuery.effective_overrides(rate_plan))
    modifiers = list(RateQuery.active_modifiers(rate_plan))
    calendar_modifiers = [m for m in modifiers if m.modifier_type in _CALENDAR_TYPES]
    segment_modifiers = [m for m in modifiers if m.modifier_type in _SEGMENT_TYPES]

    nightly = []
    for offset in range(stay_period.nights):
        night = stay_period.arrival + timedelta(days=offset)
        adjustments = []

        override = _override_covering(overrides, night)
        if override is not None:
            adjustments.append(
                LineItem(f"override:{override.id}", _override_adjustment(override, base))
            )
        for modifier in calendar_modifiers:
            if _calendar_modifier_matches(modifier, night):
                pct = modifier.config["adjustment_pct"]
                adjustments.append(
                    LineItem(f"{modifier.modifier_type}:{modifier.id}", base.percentage_of(pct))
                )

        night_total = base
        for adjustment in adjustments:
            night_total = night_total + adjustment.amount
        nightly.append(
            NightlyPrice(
                night=night, base=base, adjustments=tuple(adjustments), total=night_total
            )
        )

    nightly_subtotal = sum((n.total for n in nightly), Money(0, currency))

    stay_adjustments = []
    for modifier in segment_modifiers:
        if _segment_modifier_matches(modifier, stay_period.nights, is_corporate):
            pct = modifier.config["adjustment_pct"]
            label = f"{modifier.modifier_type}:{modifier.id}"
            stay_adjustments.append(LineItem(label, nightly_subtotal.percentage_of(pct)))

    subtotal = nightly_subtotal
    for adjustment in stay_adjustments:
        subtotal = subtotal + adjustment.amount

    floor_minor_units, ceiling_minor_units = _pricing_policy_bounds(rate_plan, stay_period)
    total = subtotal
    if ceiling_minor_units is not None and total.amount > ceiling_minor_units:
        total = Money(ceiling_minor_units, currency)
    if floor_minor_units is not None and total.amount < floor_minor_units:
        total = Money(floor_minor_units, currency)

    return PriceBreakdown(
        nightly=tuple(nightly),
        subtotal=subtotal,
        total=total,
        stay_adjustments=tuple(stay_adjustments),
        floor_minor_units=floor_minor_units,
        ceiling_minor_units=ceiling_minor_units,
    )


def _pricing_policy_bounds(rate_plan: RatePlan, stay_period) -> tuple[int | None, int | None]:
    """Reads the DDS S8 floor/ceiling contract from PolicyService.pricing_policy():
    {"floor_minor_units": int | None, "ceiling_minor_units": int | None}.
    No policy configured is a valid, unclamped state — not an error.
    """
    try:
        answer = PolicyService.pricing_policy(
            rate_plan.tenant, stay_period.arrival, rate_plan.property_id
        )
    except NoPolicyFound:
        return None, None
    if not answer:
        return None, None
    floor_value = answer.get("floor_minor_units")
    ceiling_value = answer.get("ceiling_minor_units")
    bounds = (("floor_minor_units", floor_value), ("ceiling_minor_units", ceiling_value))
    for label, value in bounds:
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
            raise InvalidPricingPolicy(
                f"pricing policy {label} must be an int or None, got {value!r}."
            )
    return floor_value, ceiling_value
