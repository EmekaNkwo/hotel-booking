"""Unit tests for the Address value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

import pytest

from apps.shared.value_objects import Address, InvalidAddress, ValueObjectError


class TestHappyPath:
    def test_constructs_from_keyword_parts(self):
        a = Address(street="12 Marina Rd", city="Lagos", country="Nigeria")

        assert a.street == "12 Marina Rd"
        assert a.city == "Lagos"
        assert a.country == "Nigeria"

    def test_omitted_parts_default_to_none(self):
        a = Address(city="Lagos")

        assert a.street is None
        assert a.region is None
        assert a.postal_code is None

    def test_str_joins_present_parts(self):
        a = Address(street="12 Marina Rd", city="Lagos", country="Nigeria")

        assert str(a) == "12 Marina Rd, Lagos, Nigeria"


class TestValidationFailures:
    @pytest.mark.parametrize(
        ("field", "bad"),
        [("street", 12), ("city", ["Lagos"]), ("region", 42)],
    )
    def test_rejects_a_non_string_part(self, field, bad):
        with pytest.raises(InvalidAddress):
            Address(**{field: bad})

    def test_rejects_an_entirely_empty_address(self):
        with pytest.raises(InvalidAddress):
            Address()

    def test_rejects_when_every_part_is_blank(self):
        with pytest.raises(InvalidAddress):
            Address(street="  ", city="", region="")

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            Address(street=5)


class TestEquality:
    def test_equal_by_value(self):
        a = Address(city="Lagos", country="Nigeria")
        b = Address(city="Lagos", country="Nigeria")

        assert a == b

    def test_different_parts_are_not_equal(self):
        assert Address(city="Lagos") != Address(city="Abuja")

    def test_hashable(self):
        a = Address(city="Lagos")
        assert len({a, a}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        a = Address(city="Lagos")

        with pytest.raises(AttributeError):
            a.city = "Abuja"


class TestBusinessOperations:
    def test_partial_address_is_valid(self):
        a = Address(country="Nigeria")

        assert str(a) == "Nigeria"

    def test_parts_are_stripped_for_stable_equality(self):
        assert Address(city="  Lagos  ") == Address(city="Lagos")

    def test_str_omits_none_parts(self):
        a = Address(street="12 Marina Rd", country="Nigeria")

        assert str(a) == "12 Marina Rd, Nigeria"


class TestEdgeCases:
    def test_error_message_names_the_offending_field(self):
        with pytest.raises(InvalidAddress, match="street"):
            Address(street=5)
