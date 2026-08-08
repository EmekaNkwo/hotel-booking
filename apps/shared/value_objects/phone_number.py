"""PhoneNumber — an E.164 canonical identifier, as a value object.

The bug this prevents: one phone line written many ways (``08012345678``,
``+2348012345678``, ``+1 (415) 555-2671``) being treated as several different
numbers. ``PhoneNumber`` standardizes on E.164 — the international format — so
every stored value is the single canonical representation of that line.

A phone number is an *identifier*, not a numeric value: you never add two
numbers, never sort them numerically, and leading zeros in national formats are
significant. That is why this object stores a canonical *string* (``.e164``),
rejects non-strings, and exposes no arithmetic.

Validation vs normalization:
- Validation rejects *impossible* values (not an E.164 shape).
- Normalization collapses the decoration of an E.164 (spaces, dashes, dots,
  parentheses) into the canonical dialable form.
- Converting *national* formats (``0801...``, ``(415)...``) to E.164 requires
  region-aware logic (trunk-prefix rules per country) and is deliberately
  deferred to a libphonenumber-style upgrade path — not this module.
"""

import re
from dataclasses import dataclass

from apps.shared.value_objects.exceptions import InvalidPhoneNumber

# + 1-15 digits; the first digit (start of the country code) is never zero.
_E164_PATTERN = re.compile(r"\+[1-9]\d{1,14}")

# Decoration that may wrap a valid E.164 in user-facing input.
_SEPARATORS = (" ", "-", ".", "(", ")")


def _normalize_e164(raw: str) -> str:
    for sep in _SEPARATORS:
        raw = raw.replace(sep, "")
    return raw


@dataclass(frozen=True, slots=True)
class PhoneNumber:
    """A canonical E.164 phone number, e.g. ``"+2348012345678"``."""
    e164: str

    def __post_init__(self) -> None:
        if not isinstance(self.e164, str):
            raise InvalidPhoneNumber(
                f"PhoneNumber must be a string (E.164, with +), got {self.e164!r}."
            )
        normalized = _normalize_e164(self.e164)
        if not _E164_PATTERN.fullmatch(normalized):
            raise InvalidPhoneNumber(
                f"Invalid phone number {self.e164!r}: "
                "expected E.164 format, e.g. '+2348012345678'."
            )
        object.__setattr__(self, "e164", normalized)

    def __str__(self) -> str:
        return self.e164
