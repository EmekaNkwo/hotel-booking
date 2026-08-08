"""Unit tests for the StayPeriod value object.

Test order follows the M1.1 convention:
happy path → validation failures → equality → immutability → business operations → edge cases.
"""

from datetime import date

import pytest

from apps.shared.value_objects import (
    DateRange,
    InvalidStayPeriod,
    StayPeriod,
)

D1 = date(2026, 8, 10)
D2 = date(2026, 8, 12)  # 2 nights


class TestHappyPath:
    def test_constructs_from_arrival_and_departure(self):
        p = StayPeriod(D1, D2)

        assert p.arrival == D1
        assert p.departure == D2

    def test_nights_is_departure_minus_arrival(self):
        assert StayPeriod(D1, date(2026, 8, 15)).nights == 5

    def test_as_date_range_returns_a_matching_range(self):
        p = StayPeriod(D1, D2)
        r = p.as_date_range()

        assert isinstance(r, DateRange)
        assert r.start == D1
        assert r.end == D2

    def test_str_uses_hotel_vocabulary(self):
        s = str(StayPeriod(D1, D2))

        assert "2 night" in s


class TestValidationFailures:
    @pytest.mark.parametrize(
        ("arrival", "departure"),
        [
            (D1, D1),  # same day — zero-length stays are forbidden
            (D2, D1),  # departure before arrival
        ],
    )
    def test_rejects_departure_not_strictly_after_arrival(self, arrival, departure):
        with pytest.raises(InvalidStayPeriod):
            StayPeriod(arrival, departure)

    @pytest.mark.parametrize("bad", ["2026-08-10", None])
    def test_rejects_non_date_bounds(self, bad):
        with pytest.raises(InvalidStayPeriod):
            StayPeriod(bad, D2)

    def test_failure_is_catchable_as_value_error(self):
        with pytest.raises(ValueError):
            StayPeriod(D2, D1)


class TestEquality:
    def test_equal_by_value(self):
        assert StayPeriod(D1, D2) == StayPeriod(D1, D2)

    def test_different_periods_are_not_equal(self):
        assert StayPeriod(D1, D2) != StayPeriod(D1, date(2026, 8, 15))

    def test_hashable(self):
        assert len({StayPeriod(D1, D2), StayPeriod(D1, D2)}) == 1


class TestImmutability:
    def test_assignment_raises(self):
        p = StayPeriod(D1, D2)

        with pytest.raises(AttributeError):
            p.arrival = D1


class TestBusinessOperations:
    def test_nights_matches_date_range_days(self):
        """StayPeriod.nights and DateRange.days compute the same value."""
        p = StayPeriod(D1, date(2026, 8, 17))

        assert p.nights == p.as_date_range().days

    def test_one_night_stay(self):
        p = StayPeriod(D1, date(2026, 8, 11))

        assert p.nights == 1

    def test_as_date_range_bridges_to_overlaps(self):
        """Once bridged, DateRange methods like overlaps become available."""
        stay = StayPeriod(D1, D2)
        maintenance = DateRange(D2, date(2026, 8, 14))

        assert not stay.as_date_range().overlaps(maintenance)


class TestEdgeCases:
    def test_error_message_uses_hotel_language(self):
        with pytest.raises(InvalidStayPeriod, match="departure"):
            StayPeriod(D2, D1)

    def test_nightly_noun_is_singular_for_one_night(self):
        assert "1 night)" in str(StayPeriod(D1, date(2026, 8, 11)))

    def test_nightly_noun_is_plural_for_multiple_nights(self):
        assert "2 nights)" in str(StayPeriod(D1, D2))
