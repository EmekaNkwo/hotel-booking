"""Unit tests for the GuestName value object.

Test order follows the M1.1 convention:
happy path -> validation failures -> equality -> immutability -> business operations -> edge cases.
"""

import pytest

from apps.shared.value_objects import GuestName, InvalidGuestName, ValueObjectError


class TestHappyPath:
    def test_constructs_from_given_name_only(self):
        n = GuestName(given_name="Zola")

        assert n.given_name == "Zola"
        assert n.family_name == ""

    def test_constructs_with_family_name(self):
        n = GuestName(given_name="Ada", family_name="Lovelace")

        assert n.given_name == "Ada"
        assert n.family_name == "Lovelace"

    def test_display_name_defaults_to_joined_parts(self):
        n = GuestName(given_name="Ada", family_name="Lovelace")

        assert n.display_name == "Ada Lovelace"

    def test_str_returns_display_name(self):
        n = GuestName(given_name="Ada", family_name="Lovelace")

        assert str(n) == "Ada Lovelace"


class TestValidationFailures:
    def test_rejects_empty_given_name(self):
        with pytest.raises(InvalidGuestName):
            GuestName(given_name="")

    def test_rejects_blank_given_name(self):
        with pytest.raises(InvalidGuestName):
            GuestName(given_name="   ")

    def test_rejects_non_string_given_name(self):
        with pytest.raises(InvalidGuestName):
            GuestName(given_name=42)

    def test_rejects_non_string_family_name(self):
        with pytest.raises(InvalidGuestName):
            GuestName(given_name="Ada", family_name=42)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            GuestName(given_name="")


class TestEquality:
    def test_equal_by_value(self):
        a = GuestName(given_name="Ada", family_name="Lovelace")
        b = GuestName(given_name="Ada", family_name="Lovelace")

        assert a == b

    def test_different_names_are_not_equal(self):
        assert GuestName(given_name="Ada") != GuestName(given_name="Grace")

    def test_hashable(self):
        n = GuestName(given_name="Ada")
        assert len({n, n}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        n = GuestName(given_name="Ada")

        with pytest.raises(AttributeError):
            n.given_name = "Grace"


class TestBusinessOperations:
    def test_parts_are_stripped_for_stable_equality(self):
        assert GuestName(given_name="  Ada  ") == GuestName(given_name="Ada")

    def test_explicit_display_name_is_preserved(self):
        n = GuestName(given_name="Madonna", display_name="Madonna")

        assert n.display_name == "Madonna"

    def test_mononym_is_valid(self):
        n = GuestName(given_name="Madonna")

        assert n.family_name == ""
        assert n.display_name == "Madonna"

    def test_to_dict_round_trips_via_from_dict(self):
        original = GuestName(given_name="Ada", family_name="Lovelace")

        restored = GuestName.from_dict(original.to_dict())

        assert restored == original

    def test_from_dict_defaults_missing_parts(self):
        n = GuestName.from_dict({"given_name": "Ada"})

        assert n.family_name == ""
        assert n.display_name == "Ada"


class TestEdgeCases:
    def test_error_message_names_the_offending_field(self):
        with pytest.raises(InvalidGuestName, match="given_name"):
            GuestName(given_name="")

    def test_from_dict_with_empty_dict_raises(self):
        with pytest.raises(InvalidGuestName):
            GuestName.from_dict({})
