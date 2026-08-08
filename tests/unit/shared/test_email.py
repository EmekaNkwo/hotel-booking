"""Unit tests for the Email value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

import pytest

from apps.shared.value_objects import Email, InvalidEmail, ValueObjectError


class TestHappyPath:
    def test_constructs_from_a_valid_address(self):
        email = Email("john@example.com")

        assert email.address == "john@example.com"

    def test_normalizes_to_lowercase(self):
        assert Email("John@Example.com").address == "john@example.com"

    def test_strips_surrounding_whitespace(self):
        assert Email("  john@example.com  ").address == "john@example.com"

    def test_str_returns_the_canonical_address(self):
        assert str(Email("John@Example.com")) == "john@example.com"


class TestValidationFailures:
    @pytest.mark.parametrize(
        "bad",
        [
            "",                   # empty
            "john",               # no @
            "@example.com",       # empty local part
            "john@",              # empty domain
            "john@@example.com",  # two @
            "john@example",       # domain has no dot
            "john@example.",      # dot at the end — no TLD
            "john@.com",          # dot at the start — no domain name
            "john @example.com",  # whitespace in local part
            "john@exa mple.com",  # whitespace in domain
        ],
    )
    def test_rejects_a_structurally_invalid_address(self, bad):
        with pytest.raises(InvalidEmail):
            Email(bad)

    @pytest.mark.parametrize("bad", [123, None, 4.5])
    def test_rejects_a_non_string(self, bad):
        with pytest.raises(InvalidEmail):
            Email(bad)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            Email("not-an-email")


class TestEquality:
    def test_equal_after_normalization(self):
        assert Email("John@Example.com") == Email("john@example.com")

    def test_different_addresses_are_not_equal(self):
        assert Email("john@example.com") != Email("jane@example.com")

    def test_different_domains_are_not_equal(self):
        assert Email("john@example.com") != Email("john@other.com")

    def test_hashable(self):
        assert len({Email("John@Example.com"), Email("john@example.com")}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        email = Email("john@example.com")

        with pytest.raises(AttributeError):
            email.address = "jane@example.com"


class TestBusinessOperations:
    def test_normalization_is_idempotent(self):
        once = Email("JOHN@EXAMPLE.COM")
        twice = Email(once.address)

        assert once == twice

    def test_hash_and_equality_agree(self):
        a = Email("John@Example.com")
        b = Email("john@example.com")

        assert hash(a) == hash(b)


class TestEdgeCases:
    def test_keeps_a_plus_tag_intact(self):
        assert Email("john+booking@example.com").address == "john+booking@example.com"

    def test_error_message_names_the_offending_value(self):
        with pytest.raises(InvalidEmail, match="bad@address"):
            Email("bad@address")
