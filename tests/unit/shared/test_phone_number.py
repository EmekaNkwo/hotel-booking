"""Unit tests for the PhoneNumber value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

import pytest

from apps.shared.value_objects import InvalidPhoneNumber, PhoneNumber, ValueObjectError


class TestHappyPath:
    def test_constructs_from_canonical_e164(self):
        phone = PhoneNumber("+2348012345678")

        assert phone.e164 == "+2348012345678"

    def test_accepts_a_short_country_code(self):
        assert PhoneNumber("+14155552671").e164 == "+14155552671"

    def test_normalizes_formatted_e164(self):
        assert PhoneNumber("+1 (415) 555-2671").e164 == "+14155552671"

    def test_str_returns_the_canonical_value(self):
        assert str(PhoneNumber("+2348012345678")) == "+2348012345678"


class TestValidationFailures:
    @pytest.mark.parametrize(
        "bad",
        [
            "",                    # empty
            "+",                   # plus only
            "08012345678",         # bare national format — E.164 is required
            "+0123456789",         # country code starting with zero
            "+abc",                # letters
            "++2348012345678",     # double international prefix
            "2348012345678",       # missing the international +
            "+1*555",              # a character that is not a valid separator
        ],
    )
    def test_rejects_a_non_e164_value(self, bad):
        with pytest.raises(InvalidPhoneNumber):
            PhoneNumber(bad)

    @pytest.mark.parametrize("bad", [14155552671, None, 4.5])
    def test_rejects_a_non_string(self, bad):
        # An int is NOT a phone number — an identifier is a canonical string.
        with pytest.raises(InvalidPhoneNumber):
            PhoneNumber(bad)

    def test_rejects_more_than_15_digits(self):
        with pytest.raises(InvalidPhoneNumber):
            PhoneNumber("+1" + "2" * 15)  # 16 digits total

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            PhoneNumber("not-a-number")


class TestEquality:
    def test_equal_when_identical(self):
        assert PhoneNumber("+2348012345678") == PhoneNumber("+2348012345678")

    def test_equal_after_normalization(self):
        assert PhoneNumber("+1 (415) 555-2671") == PhoneNumber("+14155552671")

    def test_different_numbers_are_not_equal(self):
        assert PhoneNumber("+2348012345678") != PhoneNumber("+2348112345678")

    def test_hashable(self):
        assert len({PhoneNumber("+2348012345678"), PhoneNumber("+2348012345678")}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        phone = PhoneNumber("+2348012345678")

        with pytest.raises(AttributeError):
            phone.e164 = "+14155552671"


class TestBusinessOperations:
    def test_normalization_is_idempotent(self):
        once = PhoneNumber("+1 (415) 555-2671")
        twice = PhoneNumber(once.e164)

        assert once == twice

    def test_hash_and_equality_agree_after_normalization(self):
        a = PhoneNumber("+1 (415) 555-2671")
        b = PhoneNumber("+14155552671")

        assert hash(a) == hash(b)


class TestEdgeCases:
    def test_maximum_15_digits_is_valid(self):
        assert PhoneNumber("+1" + "2" * 14).e164 == "+1" + "2" * 14

    def test_error_message_names_the_offending_value(self):
        with pytest.raises(InvalidPhoneNumber, match="08012345678"):
            PhoneNumber("08012345678")

    def test_dots_are_normalized(self):
        assert PhoneNumber("+234.801.234.5678").e164 == "+2348012345678"
