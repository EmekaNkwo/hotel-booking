"""Currency — an ISO-4217 code, as a value object.

The bug it eliminates: ``"NGN"``, ``"ngn"``, ``"₦"`` and ``"NGM"`` (a typo) are
all *strings*, and nothing stops one part of the codebase treating them as
different currencies while another treats them as the same. A ``Currency`` that
refuses anything but a 3-letter uppercase code turns "is this a currency?" into
a type — checked once, at construction, by everyone who builds one.

Validation scope: M1.1 validates *structure* only — any 3 uppercase letters
(e.g. ``"ABC"``) is accepted. Semantic validation against the ISO-4217 registry
is intentionally deferred until a real consumer requires it.
"""

from dataclasses import dataclass

from apps.shared.value_objects.exceptions import InvalidCurrency


def _is_valid_code(code: object) -> bool:
    return (
        isinstance(code, str)
        and len(code) == 3
        and code.isascii()
        and code.isalpha()
        and code.isupper()
    )


@dataclass(frozen=True, slots=True)
class Currency:
    """An ISO-4217 currency code, e.g. ``"NGN"`` or ``"USD"``.

    Immutable and hashable (frozen) with no per-instance dict (slots): two
    currencies are equal iff their codes are equal.
    """

    code: str

    def __post_init__(self) -> None:
        if not _is_valid_code(self.code):
            raise InvalidCurrency(
                f"Invalid currency code {self.code!r}: "
                "expected exactly 3 uppercase letters."
            )

    def __str__(self) -> str:
        return self.code


# Common platform currencies. Post-class assignment: a slotted dataclass cannot
# reference itself during its own definition.
Currency.NGN = Currency("NGN")
Currency.USD = Currency("USD")
Currency.EUR = Currency("EUR")
Currency.GBP = Currency("GBP")
