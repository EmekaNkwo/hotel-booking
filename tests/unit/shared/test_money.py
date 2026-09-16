"""Unit tests for the Money value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

from operator import lt

import pytest

from apps.shared.value_objects import (
    Currency,
    CurrencyMismatch,
    InvalidMoney,
    Money,
    ValueObjectError,
)

NGN = Currency.NGN
USD = Currency.USD


class TestHappyPath:
    def test_constructs_from_minor_units_and_currency(self):
        money = Money(45000, NGN)

        assert money.amount == 45000
        assert money.currency == NGN

    def test_allows_negative_amounts_for_refunds(self):
        assert Money(-5000, NGN).amount == -5000

    def test_allows_zero(self):
        assert Money(0, NGN).amount == 0

    def test_str_reports_raw_minor_units_and_code(self):
        assert str(Money(45000, NGN)) == "45000 NGN"


class TestValidationFailures:
    @pytest.mark.parametrize("bad", [45.5, "45000", None, 45.0])
    def test_rejects_a_non_int_amount(self, bad):
        with pytest.raises(InvalidMoney):
            Money(bad, NGN)

    def test_rejects_a_bool_amount(self):
        # bool is an int subclass; True must not silently mean 1 minor unit.
        with pytest.raises(InvalidMoney):
            Money(True, NGN)

    @pytest.mark.parametrize("bad", ["NGN", None, 42])
    def test_rejects_a_non_currency_currency(self, bad):
        with pytest.raises(InvalidMoney):
            Money(45000, bad)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            Money(45.5, NGN)


class TestEquality:
    def test_equal_by_value(self):
        assert Money(45000, NGN) == Money(45000, NGN)

    def test_same_amount_in_different_currencies_is_not_equal(self):
        assert Money(45000, NGN) != Money(45000, USD)

    def test_hashable(self):
        assert len({Money(45000, NGN), Money(45000, NGN)}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        money = Money(45000, NGN)

        with pytest.raises(AttributeError):
            money.amount = 1

        with pytest.raises(AttributeError):
            money.currency = USD


class TestBusinessOperations:
    def test_adds_same_currency(self):
        assert Money(100, NGN) + Money(50, NGN) == Money(150, NGN)

    def test_subtracts_same_currency(self):
        assert Money(100, NGN) - Money(30, NGN) == Money(70, NGN)

    def test_multiplies_by_a_whole_number(self):
        assert Money(100, NGN) * 3 == Money(300, NGN)
        assert 3 * Money(100, NGN) == Money(300, NGN)

    def test_negates_for_refunds(self):
        assert -Money(100, NGN) == Money(-100, NGN)

    def test_sum_over_a_list(self):
        assert sum([Money(100, NGN), Money(50, NGN), Money(25, NGN)]) == Money(175, NGN)

    def test_arithmetic_returns_a_fresh_object(self):
        original = Money(100, NGN)
        result = original + Money(50, NGN)

        assert original == Money(100, NGN)  # operands are never mutated
        assert result is not original

    def test_percentage_of_exact_division(self):
        assert Money(200, NGN).percentage_of(50) == Money(100, NGN)

    def test_percentage_of_negative_percent_is_a_discount(self):
        assert Money(200, NGN).percentage_of(-10) == Money(-20, NGN)

    def test_percentage_of_zero_percent_is_zero(self):
        assert Money(200, NGN).percentage_of(0) == Money(0, NGN)

    def test_percentage_of_preserves_currency(self):
        assert Money(200, USD).percentage_of(10).currency == USD


class TestEdgeCases:
    def test_mixed_currency_addition_raises_with_context(self):
        with pytest.raises(CurrencyMismatch) as exc_info:
            Money(100, NGN) + Money(100, USD)

        assert exc_info.value.left == NGN
        assert exc_info.value.right == USD

    def test_mixed_currency_subtraction_raises(self):
        with pytest.raises(CurrencyMismatch):
            Money(100, NGN) - Money(100, USD)

    def test_float_multiplier_is_rejected(self):
        with pytest.raises(TypeError):
            Money(100, NGN) * 2.5

    def test_adding_a_bare_number_is_rejected(self):
        with pytest.raises(TypeError):
            Money(100, NGN) + 1

    def test_ordering_is_intentionally_unsupported(self):
        # Comparison operators are deliberately deferred in M1.1 — this test
        # turns that deferral into a decision that must be revisited on purpose.
        # operator.lt invokes __lt__ explicitly so the intent survives linting.
        with pytest.raises(TypeError):
            lt(Money(100, NGN), Money(200, NGN))

    def test_error_message_names_both_currencies(self):
        with pytest.raises(CurrencyMismatch, match="NGN.*USD"):
            Money(100, NGN) + Money(100, USD)

    @pytest.mark.parametrize(
        ("amount", "percent", "expected"),
        [
            (1, 50, 1),  # 0.5 -> rounds up (away from zero)
            (3, 50, 2),  # 1.5 -> rounds up
            (-1, 50, -1),  # -0.5 -> rounds away from zero, i.e. down
            (1, -50, -1),  # -0.5 -> rounds away from zero
            (5, 10, 1),  # 0.5 -> rounds up
        ],
    )
    def test_percentage_of_rounds_half_up_away_from_zero(self, amount, percent, expected):
        assert Money(amount, NGN).percentage_of(percent) == Money(expected, NGN)

    def test_percentage_of_rejects_a_float_percent(self):
        with pytest.raises(InvalidMoney):
            Money(100, NGN).percentage_of(12.5)

    def test_percentage_of_rejects_a_bool_percent(self):
        with pytest.raises(InvalidMoney):
            Money(100, NGN).percentage_of(True)
