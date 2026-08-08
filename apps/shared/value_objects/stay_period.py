"""StayPeriod — a guest's arrival-to-departure span, as a value object.

The bug this prevents: using a generic ``DateRange`` for stays erases the word
"arrival" from the codebase. When a service method takes a ``DateRange``, its
caller cannot tell whether it represents a rate window, a maintenance shutdown,
or a guest's actual stay. ``StayPeriod`` preserves the hospitality vocabulary:
``arrival`` and ``departure`` are business events, not just two dates.

StayPeriod validates the same invariant as DateRange (departure > arrival) and
bridges to DateRange via ``as_date_range()`` for code that needs generic
interval operations.
"""

from dataclasses import dataclass
from datetime import date

from apps.shared.value_objects.date_range import DateRange
from apps.shared.value_objects.exceptions import InvalidStayPeriod


@dataclass(frozen=True, slots=True)
class StayPeriod:
    """A guest's arrival-to-departure span. The departure date is NOT part of
    the stay (half-open convention: ``[arrival, departure)``).
    """

    arrival: date
    departure: date

    def __post_init__(self) -> None:
        if not isinstance(self.arrival, date) or not isinstance(self.departure, date):
            raise InvalidStayPeriod(
                f"StayPeriod bounds must be date objects, "
                f"got arrival={self.arrival!r}, departure={self.departure!r}."
            )
        if not self.departure > self.arrival:
            raise InvalidStayPeriod(
                "StayPeriod departure must be after arrival, "
                f"got {self.arrival.isoformat()} → {self.departure.isoformat()}."
            )

    def __str__(self) -> str:
        night_word = "night" if self.nights == 1 else "nights"
        return (
            f"StayPeriod({self.arrival.isoformat()} → "
            f"{self.departure.isoformat()}, {self.nights} {night_word})"
        )

    @property
    def nights(self) -> int:
        """Number of nights in the stay."""
        return (self.departure - self.arrival).days

    def as_date_range(self) -> DateRange:
        """Bridge to the generic interval when DateRange operations are needed."""
        return DateRange(self.arrival, self.departure)
