"""GuestName — a structured personal name, as a value object.

The bug this prevents: "first/last name" split into bare, separately-passed
strings drifts apart across a stay — a booking form, a PMS import, and a front
desk edit each spell the same guest differently, and nothing ever compares
them as one identity. ``GuestName`` binds the parts together so they travel
and compare as a unit, and derives a single display form once instead of every
caller re-joining strings its own way.

Not every culture uses a family name (mononyms are real), so only
``given_name`` is required — the one part a guest record cannot function
without. Whether a *booking* or a *legal document* additionally requires a
family name is a business rule for later contexts (Booking, Guest Profile),
not an invariant here.
"""

from dataclasses import dataclass

from apps.shared.value_objects.exceptions import InvalidGuestName

_OPTIONAL_STRING_FIELDS = ("family_name", "display_name")


@dataclass(frozen=True, slots=True)
class GuestName:
    """A structured guest name. ``display_name`` defaults to the joined parts."""

    given_name: str
    family_name: str = ""
    display_name: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.given_name, str) or not self.given_name.strip():
            raise InvalidGuestName(
                f"GuestName requires a non-empty given_name, got {self.given_name!r}."
            )
        for field in _OPTIONAL_STRING_FIELDS:
            value = getattr(self, field)
            if not isinstance(value, str):
                raise InvalidGuestName(f"GuestName.{field} must be a string, got {value!r}.")

        object.__setattr__(self, "given_name", self.given_name.strip())
        object.__setattr__(self, "family_name", self.family_name.strip())
        if not self.display_name.strip():
            joined = " ".join(part for part in (self.given_name, self.family_name) if part)
            object.__setattr__(self, "display_name", joined)
        else:
            object.__setattr__(self, "display_name", self.display_name.strip())

    def __str__(self) -> str:
        return self.display_name

    def to_dict(self) -> dict:
        """The JSONB-storable form (``GuestProfile.name``)."""
        return {
            "given_name": self.given_name,
            "family_name": self.family_name,
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GuestName":
        """Reconstruct from the stored JSONB form. Missing parts default empty."""
        return cls(
            given_name=data.get("given_name", ""),
            family_name=data.get("family_name", ""),
            display_name=data.get("display_name", ""),
        )
