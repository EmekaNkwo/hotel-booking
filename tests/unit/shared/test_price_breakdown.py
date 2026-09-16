"""Unit tests for the PriceBreakdown value object (and its LineItem/NightlyPrice parts).

Test order follows the M1.1 convention:
happy path -> validation failures -> equality -> immutability -> business operations -> edge cases.
"""

from datetime import date

import pytest

from apps.shared.value_objects import (
    Currency,
    InvalidPriceBreakdown,
    LineItem,
    Money,
    NightlyPrice,
    PriceBreakdown,
    ValueObjectError,
)

NGN = Currency.NGN
USD = Currency.USD


def _night(day, base=10000, adjustments=(), total=None):
    total = Money(base, NGN) if total is None else total
    return NightlyPrice(
        night=day,
        base=Money(base, NGN),
        adjustments=adjustments,
        total=total,
    )


class TestHappyPath:
    def test_constructs_single_night_breakdown(self):
        n = _night(date(2026, 1, 1))
        pb = PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        assert pb.total == Money(10000, NGN)
        assert pb.subtotal == Money(10000, NGN)
        assert pb.currency == NGN

    def test_constructs_multi_night_breakdown(self):
        n1 = _night(date(2026, 1, 1))
        n2 = _night(date(2026, 1, 2))
        pb = PriceBreakdown(nightly=(n1, n2), subtotal=Money(20000, NGN), total=Money(20000, NGN))

        assert len(pb.nightly) == 2

    def test_str_reports_total_and_night_count(self):
        n = _night(date(2026, 1, 1))
        pb = PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        assert str(pb) == "PriceBreakdown(10000 NGN, 1 nights)"

    def test_line_item_to_dict(self):
        item = LineItem(label="weekend", amount=Money(1500, NGN))

        assert item.to_dict() == {
            "label": "weekend",
            "amount_minor_units": 1500,
            "currency": "NGN",
        }


class TestValidationFailures:
    def test_rejects_empty_nightly(self):
        with pytest.raises(InvalidPriceBreakdown):
            PriceBreakdown(nightly=(), subtotal=Money(0, NGN), total=Money(0, NGN))

    def test_rejects_mismatched_currency_between_total_and_subtotal(self):
        n = _night(date(2026, 1, 1))
        with pytest.raises(InvalidPriceBreakdown):
            PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, USD))

    def test_rejects_nightly_currency_not_matching_breakdown(self):
        n_ngn = _night(date(2026, 1, 1))
        with pytest.raises(InvalidPriceBreakdown):
            PriceBreakdown(nightly=(n_ngn,), subtotal=Money(10000, USD), total=Money(10000, USD))

    def test_rejects_negative_total(self):
        n = _night(date(2026, 1, 1), total=Money(0, NGN))
        with pytest.raises(InvalidPriceBreakdown):
            PriceBreakdown(nightly=(n,), subtotal=Money(0, NGN), total=Money(-1, NGN))

    def test_rejects_subtotal_not_matching_sum_of_nights(self):
        n1 = _night(date(2026, 1, 1))
        n2 = _night(date(2026, 1, 2))
        with pytest.raises(InvalidPriceBreakdown, match="subtotal"):
            PriceBreakdown(nightly=(n1, n2), subtotal=Money(15000, NGN), total=Money(15000, NGN))

    def test_rejects_subtotal_ignoring_stay_adjustments(self):
        n = _night(date(2026, 1, 1))
        with pytest.raises(InvalidPriceBreakdown, match="subtotal"):
            PriceBreakdown(
                nightly=(n,),
                subtotal=Money(10000, NGN),  # ignores the -1000 stay adjustment below
                total=Money(9000, NGN),
                stay_adjustments=(LineItem("long_stay", Money(-1000, NGN)),),
            )

    def test_rejects_stay_adjustment_currency_mismatch(self):
        n = _night(date(2026, 1, 1))
        with pytest.raises(InvalidPriceBreakdown):
            PriceBreakdown(
                nightly=(n,),
                subtotal=Money(10100, NGN),
                total=Money(10100, NGN),
                stay_adjustments=(LineItem("corporate", Money(100, USD)),),
            )

    def test_rejects_non_int_floor(self):
        n = _night(date(2026, 1, 1))
        with pytest.raises(InvalidPriceBreakdown):
            PriceBreakdown(
                nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN),
                floor_minor_units="1000",
            )

    def test_nightly_price_rejects_negative_total(self):
        with pytest.raises(InvalidPriceBreakdown):
            NightlyPrice(
                night=date(2026, 1, 1), base=Money(10000, NGN), adjustments=(),
                total=Money(-1, NGN),
            )

    def test_nightly_price_rejects_adjustment_currency_mismatch(self):
        with pytest.raises(InvalidPriceBreakdown):
            NightlyPrice(
                night=date(2026, 1, 1),
                base=Money(10000, NGN),
                adjustments=(LineItem("bad", Money(100, USD)),),
                total=Money(10100, NGN),
            )

    def test_line_item_rejects_blank_label(self):
        with pytest.raises(InvalidPriceBreakdown):
            LineItem(label="  ", amount=Money(100, NGN))

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            PriceBreakdown(nightly=(), subtotal=Money(0, NGN), total=Money(0, NGN))


class TestEquality:
    def test_equal_by_value(self):
        n1 = _night(date(2026, 1, 1))
        n2 = _night(date(2026, 1, 1))
        a = PriceBreakdown(nightly=(n1,), subtotal=Money(10000, NGN), total=Money(10000, NGN))
        b = PriceBreakdown(nightly=(n2,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        assert a == b

    def test_different_totals_are_not_equal(self):
        n = _night(date(2026, 1, 1))
        a = PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN))
        b = PriceBreakdown(
            nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN),
            floor_minor_units=5000,
        )

        assert a != b


class TestImmutability:
    def test_assignment_raises(self):
        n = _night(date(2026, 1, 1))
        pb = PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        with pytest.raises(AttributeError):
            pb.total = Money(0, NGN)


class TestBusinessOperations:
    def test_was_clamped_false_when_total_equals_subtotal(self):
        n = _night(date(2026, 1, 1))
        pb = PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        assert pb.was_clamped is False

    def test_was_clamped_true_when_ceiling_lowered_the_total(self):
        n = _night(date(2026, 1, 1))
        pb = PriceBreakdown(
            nightly=(n,), subtotal=Money(10000, NGN), total=Money(8000, NGN),
            ceiling_minor_units=8000,
        )

        assert pb.was_clamped is True

    def test_stay_adjustments_apply_once_not_per_night(self):
        n1 = _night(date(2026, 1, 1))
        n2 = _night(date(2026, 1, 2))
        pb = PriceBreakdown(
            nightly=(n1, n2),
            subtotal=Money(18000, NGN),
            total=Money(18000, NGN),
            stay_adjustments=(LineItem("long_stay", Money(-2000, NGN)),),
        )

        assert pb.subtotal == Money(18000, NGN)
        assert len(pb.stay_adjustments) == 1

    def test_to_dict_round_trips_shape(self):
        n = _night(date(2026, 1, 1), adjustments=(LineItem("weekend", Money(500, NGN)),))
        pb = PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        data = pb.to_dict()

        assert data["total_minor_units"] == 10000
        assert data["currency"] == "NGN"
        assert data["nightly"][0]["adjustments"][0]["label"] == "weekend"

    def test_deterministic_construction_from_identical_inputs(self):
        n1 = _night(date(2026, 1, 1))
        n2 = _night(date(2026, 1, 1))
        a = PriceBreakdown(nightly=(n1,), subtotal=Money(10000, NGN), total=Money(10000, NGN))
        b = PriceBreakdown(nightly=(n2,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        assert a == b
        assert a.to_dict() == b.to_dict()


class TestEdgeCases:
    def test_error_message_names_the_offending_field(self):
        n = _night(date(2026, 1, 1))
        with pytest.raises(InvalidPriceBreakdown, match="floor_minor_units"):
            PriceBreakdown(
                nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN),
                floor_minor_units=1.5,
            )

    def test_single_night_stay_is_valid(self):
        n = _night(date(2026, 1, 1))
        pb = PriceBreakdown(nightly=(n,), subtotal=Money(10000, NGN), total=Money(10000, NGN))

        assert len(pb.nightly) == 1
