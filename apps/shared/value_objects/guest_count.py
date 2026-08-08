"""GuestCount — adults, children and (optional) infants, as a value object.

The bug this prevents: search and pricing code passing bare ints around means
``2`` might mean two adults, two children, or two people — and nothing stops a
rate being quoted for ``-1`` guests. ``GuestCount`` makes a party a typed,
comparable object.

Validation boundary (structural only): a guest count is invalid when it has
negative or non-integer people, or zero people. Anything that needs business
context — "at least one adult", room capacity, age-based pricing, max party
size — is a *business rule* that belongs to a later bounded context (Policy,
Rooms, Pricing, Booking), not here (DR-10 "ask, don't embed"). Structure in,
policy out.
"""

from dataclasses import dataclass

from apps.shared.value_objects.exceptions import InvalidGuestCount


@dataclass(frozen=True, slots=True)
class GuestCount:
    """A party composition: adults, children, and optional infants."""

    adults: int
    children: int
    infants: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("adults", self.adults),
            ("children", self.children),
            ("infants", self.infants),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidGuestCount(f"{label} must be a non-negative int, got {value!r}.")
        if self.total_guests < 1:
            raise InvalidGuestCount("GuestCount must describe at least one guest.")

    def __str__(self) -> str:
        parts = []
        if self.adults:
            parts.append(f"{self.adults} adult{'s' if self.adults != 1 else ''}")
        if self.children:
            parts.append(f"{self.children} child{'ren' if self.children != 1 else ''}")
        if self.infants:
            parts.append(f"{self.infants} infant{'s' if self.infants != 1 else ''}")
        return ", ".join(parts)

    @property
    def total_guests(self) -> int:
        """Total people in the party, infants included."""
        return self.adults + self.children + self.infants
