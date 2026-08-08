"""Unit tests for the DateRange value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

from datetime import date

import pytest

from apps.shared.value_objects import DateRange, InvalidDateRange

# August 2026 — a realistic mid-summer window.
D1 = date(2026, 8, 10)
D2 = date(2026, 8, 12)  # D1 + 2 nights
D3 = date(2026, 8, 14)  # D1 + 4 nights


class TestHappyPath:
    def test_constructs_from_start_and_end(self):
        r = DateRange(D1, D2)

        assert r.start == D1
        assert r.end == D2

    def test_days_is_end_minus_start(self):
        assert DateRange(D1, D3).days == 4

    def test_str_uses_half_open_notation(self):
        assert str(DateRange(D1, D2)) == "[2026-08-10, 2026-08-12)"


class TestValidationFailures:
    @pytest.mark.parametrize(
        ("start", "end"),
        [
            (D1, D1),  # same day — zero-length range is forbidden
            (D3, D1),  # reversed
            (D2, D1),  # end before start
        ],
    )
    def test_rejects_end_not_strictly_after_start(self, start, end):
        with pytest.raises(InvalidDateRange):
            DateRange(start, end)

    @pytest.mark.parametrize("bad", ["2026-08-10", None, 20260810])
    def test_rejects_non_date_bounds(self, bad):
        with pytest.raises(InvalidDateRange):
            DateRange(bad, D2)

    def test_failure_is_catchable_as_value_error(self):
        with pytest.raises(ValueError):
            DateRange(D3, D1)


class TestEquality:
    def test_equal_by_value(self):
        assert DateRange(D1, D2) == DateRange(D1, D2)

    def test_different_ranges_are_not_equal(self):
        assert DateRange(D1, D2) != DateRange(D1, D3)

    def test_hashable(self):
        assert len({DateRange(D1, D2), DateRange(D1, D2)}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        r = DateRange(D1, D2)

        with pytest.raises(AttributeError):
            r.start = D3


class TestBusinessOperations:
    def test_days_derives_length(self):
        """A4-night stay between two dates is measured as end − start."""
        assert DateRange(D1, D3).days == 4

    def test_overlaps_true_when_ranges_share_nights(self):
        """A reservation spanning D1–D3 overlaps with a rate window starting at D2."""
        assert DateRange(D1, D3).overlaps(DateRange(D2, D3))

    def test_overlaps_false_for_disjoint_ranges(self):
        """A maintenance window in September cannot overlap with an August reservation."""
        assert not DateRange(D1, D2).overlaps(
            DateRange(date(2026, 9, 1), date(2026, 9, 5))
        )

    def test_overlaps_false_for_adjacent_ranges(self):
        """[10, 12) and [12, 14) touch at Aug 12 but share no night."""
        assert not DateRange(D1, D2).overlaps(DateRange(D2, D3))

    def test_contains_true_for_an_internal_day(self):
        assert DateRange(D1, D3).contains(D2)

    def test_contains_true_for_the_start_day(self):
        assert DateRange(D1, D3).contains(D1)

    def test_contains_false_for_the_end_day(self):
        """The exclusive end: the checkout day is NOT inside the range."""
        assert not DateRange(D1, D3).contains(D3)

    def test_contains_false_outside_the_range(self):
        assert not DateRange(D1, D3).contains(date(2026, 8, 9))


class TestEdgeCases:
    def test_adjacent_ranges_tile_exactly(self):
        """Half-open composition: [d1,d2).days + [d2,d3).days == [d1,d3).days."""
        first = DateRange(D1, D2)
        second = DateRange(D2, D3)

        assert first.days + second.days == DateRange(D1, D3).days

    def test_overlaps_rejects_a_non_date_range(self):
        with pytest.raises(TypeError):
            DateRange(D1, D2).overlaps((D1, D2))

    def test_error_message_names_the_invalid_pair(self):
        with pytest.raises(InvalidDateRange, match="end"):
            DateRange(D3, D1)
