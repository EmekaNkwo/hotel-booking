"""Unit tests for the GuestCount value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

import pytest

from apps.shared.value_objects import GuestCount, InvalidGuestCount, ValueObjectError


class TestHappyPath:
    def test_constructs_from_adults_and_children(self):
        g = GuestCount(2, 1)

        assert g.adults == 2
        assert g.children == 1
        assert g.infants == 0  # optional, defaults to zero

    def test_accepts_an_explicit_infant_count(self):
        assert GuestCount(2, 1, 1).infants == 1

    def test_total_guests_is_the_sum(self):
        assert GuestCount(2, 1, 1).total_guests == 4

    def test_str_reads_naturally(self):
        assert str(GuestCount(2, 1)) == "2 adults, 1 child"

    def test_str_includes_infants_when_present(self):
        assert str(GuestCount(2, 1, 1)) == "2 adults, 1 child, 1 infant"


class TestValidationFailures:
    @pytest.mark.parametrize("bad", [-1, 1.5, "2", True, None])
    def test_rejects_a_bad_adult_count(self, bad):
        with pytest.raises(InvalidGuestCount):
            GuestCount(bad, 1)

    @pytest.mark.parametrize("bad", [-1, 1.5])
    def test_rejects_a_bad_child_count(self, bad):
        with pytest.raises(InvalidGuestCount):
            GuestCount(2, bad)

    @pytest.mark.parametrize("bad", [-1, 1.5])
    def test_rejects_a_bad_infant_count(self, bad):
        with pytest.raises(InvalidGuestCount):
            GuestCount(2, 1, bad)

    def test_rejects_a_zero_total(self):
        with pytest.raises(InvalidGuestCount):
            GuestCount(0, 0, 0)

    def test_failure_is_catchable_as_a_value_object_error(self):
        with pytest.raises(ValueObjectError):
            GuestCount(-1, 1)


class TestEquality:
    def test_equal_by_value(self):
        assert GuestCount(2, 1) == GuestCount(2, 1)

    def test_adults_and_children_are_not_interchangeable(self):
        assert GuestCount(2, 1) != GuestCount(1, 2)

    def test_hashable(self):
        assert len({GuestCount(2, 1), GuestCount(2, 1)}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        g = GuestCount(2, 1)

        with pytest.raises(AttributeError):
            g.adults = 3


class TestBusinessOperations:
    def test_children_only_is_structurally_valid(self):
        # "At least one adult" is a business rule owned by Policy/Booking,
        # NOT an invariant of a guest count — some segments allow minor-only
        # groups. This test pins that decision in place.
        g = GuestCount(0, 2)

        assert g.total_guests == 2

    def test_infants_count_toward_total(self):
        assert GuestCount(2, 1, 1).total_guests == 4


class TestEdgeCases:
    def test_error_message_names_the_offending_field(self):
        with pytest.raises(InvalidGuestCount, match="adults"):
            GuestCount(-2, 1)

    def test_single_adult_string_is_singular(self):
        assert str(GuestCount(1, 0)) == "1 adult"
