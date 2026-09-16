"""PriceBreakdown — the computed, auditable result of a price quote, as a value object.

The bug this prevents: a price without a paper trail. If a service only ever
returns a total ``Money``, "why is this stay ₦180,000?" has no answer — a
guest disputes a charge, and nobody can reconstruct the weekend surcharge, the
long-stay discount, and the policy ceiling that produced it. ``PriceBreakdown``
carries the per-night math AND the flat list of adjustments that produced the
final number, so the answer is always in the object itself, not in a log
somewhere.

This is a *computed* value object, not a composition one (contrast
``Address``): every field is an output of ``PricingService.price()``, never
constructed piecemeal by a caller. It is immutable and comparable — two
computations with identical inputs produce equal ``PriceBreakdown`` values
(determinism) — and it is meant to be **snapshotted** onto a future
quote/reservation/booking (DR-06): once persisted, it is never recomputed.
"""

from dataclasses import dataclass
from datetime import date

from apps.shared.value_objects.currency import Currency
from apps.shared.value_objects.exceptions import InvalidPriceBreakdown
from apps.shared.value_objects.money import Money


@dataclass(frozen=True, slots=True)
class LineItem:
    """One named adjustment (an override or a modifier) and the amount it
    contributed. ``amount`` may be negative (a discount)."""

    label: str
    amount: Money

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise InvalidPriceBreakdown(
                f"LineItem.label must be a non-empty string, got {self.label!r}."
            )
        if not isinstance(self.amount, Money):
            raise InvalidPriceBreakdown(
                f"LineItem.amount must be a Money, got {self.amount!r}."
            )
        object.__setattr__(self, "label", self.label.strip())

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "amount_minor_units": self.amount.amount,
            "currency": self.amount.currency.code,
        }


@dataclass(frozen=True, slots=True)
class NightlyPrice:
    """The base rate and every adjustment applied to a single night."""

    night: date
    base: Money
    adjustments: tuple[LineItem, ...]
    total: Money

    def __post_init__(self) -> None:
        if not isinstance(self.night, date):
            raise InvalidPriceBreakdown(
                f"NightlyPrice.night must be a date, got {self.night!r}."
            )
        if not isinstance(self.base, Money) or not isinstance(self.total, Money):
            raise InvalidPriceBreakdown("NightlyPrice.base and .total must be Money.")
        if self.total.currency != self.base.currency:
            raise InvalidPriceBreakdown(
                "NightlyPrice.total must be in the same currency as .base."
            )
        if self.total.amount < 0:
            raise InvalidPriceBreakdown("NightlyPrice.total cannot be negative.")
        if not isinstance(self.adjustments, tuple) or not all(
            isinstance(a, LineItem) for a in self.adjustments
        ):
            raise InvalidPriceBreakdown("NightlyPrice.adjustments must be a tuple of LineItem.")
        for adjustment in self.adjustments:
            if adjustment.amount.currency != self.base.currency:
                raise InvalidPriceBreakdown(
                    "NightlyPrice adjustments must be in the same currency as .base."
                )

    def to_dict(self) -> dict:
        return {
            "night": self.night.isoformat(),
            "base_minor_units": self.base.amount,
            "currency": self.base.currency.code,
            "adjustments": [a.to_dict() for a in self.adjustments],
            "total_minor_units": self.total.amount,
        }


@dataclass(frozen=True, slots=True)
class PriceBreakdown:
    """The full, auditable result of one price computation.

    ``nightly`` carries per-night factors (base rate, overrides, calendar
    modifiers — season/weekend/holiday). ``stay_adjustments`` carries
    segment modifiers (long-stay, corporate): DMS S8 treats these as a
    stay-level input, not a per-night one, so they are a flat list of
    ``LineItem``s applied once to the summed nightly total, not distributed
    across individual nights.

    ``subtotal`` = sum(nightly totals) + sum(stay_adjustments), before any
    policy floor/ceiling clamp. ``total`` is the stay-level amount after the
    clamp (DDS S8: floors/ceilings apply to the final stay total, not per
    night). When no clamp fired, ``total == subtotal``.
    """

    nightly: tuple[NightlyPrice, ...]
    subtotal: Money
    total: Money
    stay_adjustments: tuple[LineItem, ...] = ()
    floor_minor_units: int | None = None
    ceiling_minor_units: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.nightly, tuple) or not self.nightly:
            raise InvalidPriceBreakdown("PriceBreakdown.nightly must be a non-empty tuple.")
        if not all(isinstance(n, NightlyPrice) for n in self.nightly):
            raise InvalidPriceBreakdown("PriceBreakdown.nightly must contain only NightlyPrice.")
        if not isinstance(self.subtotal, Money) or not isinstance(self.total, Money):
            raise InvalidPriceBreakdown("PriceBreakdown.subtotal and .total must be Money.")
        if not isinstance(self.stay_adjustments, tuple) or not all(
            isinstance(a, LineItem) for a in self.stay_adjustments
        ):
            raise InvalidPriceBreakdown(
                "PriceBreakdown.stay_adjustments must be a tuple of LineItem."
            )
        currency = self.subtotal.currency
        if self.total.currency != currency:
            raise InvalidPriceBreakdown("PriceBreakdown.total must match .subtotal's currency.")
        if any(n.base.currency != currency for n in self.nightly):
            raise InvalidPriceBreakdown(
                "Every NightlyPrice must be in PriceBreakdown's currency — a "
                "breakdown never mixes currencies."
            )
        if any(a.amount.currency != currency for a in self.stay_adjustments):
            raise InvalidPriceBreakdown(
                "Every stay_adjustments LineItem must be in PriceBreakdown's currency."
            )
        if self.total.amount < 0 or self.subtotal.amount < 0:
            raise InvalidPriceBreakdown("PriceBreakdown amounts cannot be negative.")
        nightly_subtotal = sum((n.total for n in self.nightly), Money(0, currency))
        computed_subtotal = nightly_subtotal + sum(
            (a.amount for a in self.stay_adjustments), Money(0, currency)
        )
        if computed_subtotal != self.subtotal:
            raise InvalidPriceBreakdown(
                f"PriceBreakdown.subtotal ({self.subtotal}) does not match nightly + "
                f"stay_adjustments ({computed_subtotal})."
            )
        for label, value in (
            ("floor_minor_units", self.floor_minor_units),
            ("ceiling_minor_units", self.ceiling_minor_units),
        ):
            if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                raise InvalidPriceBreakdown(
                    f"PriceBreakdown.{label} must be an int or None, got {value!r}."
                )

    def __str__(self) -> str:
        return f"PriceBreakdown({self.total}, {len(self.nightly)} nights)"

    @property
    def currency(self) -> Currency:
        return self.total.currency

    @property
    def was_clamped(self) -> bool:
        """True if the policy floor/ceiling changed the stay total."""
        return self.total != self.subtotal

    def to_dict(self) -> dict:
        """The JSONB-storable form (a future booking's ``price_snapshot``)."""
        return {
            "nightly": [n.to_dict() for n in self.nightly],
            "stay_adjustments": [a.to_dict() for a in self.stay_adjustments],
            "subtotal_minor_units": self.subtotal.amount,
            "total_minor_units": self.total.amount,
            "currency": self.currency.code,
            "floor_minor_units": self.floor_minor_units,
            "ceiling_minor_units": self.ceiling_minor_units,
        }
