"""Address — a composition of related location fields, as a value object.

The bug this prevents: scattered bare strings (street, city, postal passed as
separate arguments) silently separate — a search by city gets a street in the
city slot, and ``"Lagos"`` never equals ``" Lagos"``. One ``Address`` value
binds the parts together so they travel and compare as a unit.

This is a *composition* value object, not a behavior one: it brings related
fields that only mean something together into one comparable value, validates
their types, and then stays out of the way. Country-specific rules (postal
formats, mandatory fields for billing) are business policy for later contexts
(Properties, Policy, Billing), not invariants here.
"""

from dataclasses import dataclass

from apps.shared.value_objects.exceptions import InvalidAddress

_FIELDS = ("street", "city", "region", "postal_code", "country")


@dataclass(frozen=True, slots=True)
class Address:
    """A location-as-value. Every part is optional; at least one is present."""

    street: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None

    def __post_init__(self) -> None:
        for field in _FIELDS:
            value = getattr(self, field)
            if value is not None and not isinstance(value, str):
                raise InvalidAddress(
                    f"Address.{field} must be a string or None, got {value!r}."
                )
            if isinstance(value, str):
                object.__setattr__(self, field, value.strip())
        if not any(getattr(self, field) for field in _FIELDS):
            raise InvalidAddress("Address must have at least one part.")

    def __str__(self) -> str:
        return ", ".join(
            part
            for part in (
                self.street,
                self.city,
                self.region,
                self.postal_code,
                self.country,
            )
            if part
        )
