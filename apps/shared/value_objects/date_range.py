"""DateRange — a half-open interval of calendar dates, as a value object.

The bug it eliminates: a "stay" stored as two loose dates lets ``departure <
arrival`` happen, and lets every consumer disagree about whether the checkout
day counts. ``DateRange`` refuses ``end <= start`` and fixes the half-open
convention ONCE: a range is ``[start, end)`` — the end date is NOT part of the
range — so ``days = end - start`` with no ``+1``, and adjacent ranges never
double-count a boundary night.

Convention: ``[start, end)``, matching Python's ``range()`` and Postgres
``daterange``, both of which exclude the upper bound.
"""

from dataclasses import dataclass
from datetime import date

from apps.shared.value_objects.exceptions import InvalidDateRange


@dataclass(frozen=True, slots=True)
class DateRange:
    """A half-open span of calendar days. ``end`` is never part of the range."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or not isinstance(self.end, date):
            raise InvalidDateRange(
                f"DateRange bounds must be date objects, "
                f"got start={self.start!r}, end={self.end!r}."
            )
        if not self.end > self.start:
            raise InvalidDateRange(
                "DateRange end must be after start, "
                f"got [{self.start.isoformat()}, {self.end.isoformat()}]."
            )

    def __str__(self) -> str:
        return f"[{self.start.isoformat()}, {self.end.isoformat()})"

    @property
    def days(self) -> int:
        """Number of days (and, for a stay, nights) spanned by the range."""
        return (self.end - self.start).days

    def contains(self, day: date) -> bool:
        """True if ``day`` is inside the range. The exclusive end is excluded."""
        return self.start <= day < self.end

    def overlaps(self, other: "DateRange") -> bool:
        """True if the ranges share at least one day.

        Strict comparisons: a range ending exactly where another starts is
        *adjacent*, not overlapping — the boundary day belongs to neither.
        """
        if not isinstance(other, DateRange):
            raise TypeError(f"DateRange.overlaps expects a DateRange, got {other!r}.")
        return self.start < other.end and self.end > other.start
