"""Unit tests for the Currency value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

import pytest

from apps.shared.value_objects import Currency, InvalidCurrency, ValueObjectError


class TestHappyPath:
    def test_constructs_from_a_valid_code(self):
        currency = Currency("NGN")

        assert currency.code == "NGN"

    def test_str_returns_the_code(self):
        assert str(Currency("NGN")) == "NGN"


class TestValidationFailures:
    @pytest.mark.parametrize(
        "bad",
        [
            "ngn",   # lowercase
            "NgN",   # mixed case
            "NG",    # too short
            "NGNA",  # too long
            "NG1",   # digit
            "N G",   # space inside
            " NGN",  # leading space
            "NGN ",  # trailing space
            "NÑG",   # non-ASCII letter
            "₦",     # currency symbol, not a code
            "",      # empty
        ],
    )
    def test_rejects_an_invalid_code(self, bad):
        with pytest.raises(InvalidCurrency):
            Currency(bad)

    def test_rejects_a_non_string(self):
        with pytest.raises(InvalidCurrency):
            Currency(123)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            Currency("ngn")

    def test_failure_is_catchable_as_a_value_error(self):
        # ValueObjectError derives from ValueError, so generic code keeps working.
        with pytest.raises(ValueError):
            Currency("ngn")


class TestEquality:
    def test_equal_by_value(self):
        assert Currency("NGN") == Currency("NGN")

    def test_different_codes_are_not_equal(self):
        assert Currency("NGN") != Currency("USD")

    def test_hashable(self):
        assert len({Currency("NGN"), Currency("NGN")}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        currency = Currency("NGN")

        with pytest.raises(AttributeError):
            currency.code = "USD"


class TestBusinessOperations:
    def test_convenience_constants(self):
        assert Currency.NGN == Currency("NGN")
        assert Currency.USD.code == "USD"

    def test_repr_is_helpful(self):
        assert repr(Currency("NGN")) == "Currency(code='NGN')"


class TestEdgeCases:
    def test_error_message_names_the_offending_value(self):
        with pytest.raises(InvalidCurrency, match="ngn"):
            Currency("ngn")
