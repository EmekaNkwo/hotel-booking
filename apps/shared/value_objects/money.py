"""Money — an integer amount in the minor units of a currency, as a value object.

The bug it eliminates: a ledger that stores prices as bare numbers lets
``5000 + 10.5`` happen — 5000 *kobo* plus a *float* of naira, silently — and
lets a NGN price be added to a USD price without anyone noticing. ``Money``
makes both impossible: ``amount`` must be an ``int`` (never a float), and
addition raises ``CurrencyMismatch`` before two different currencies ever touch.
The failure becomes loud, at the boundary, instead of silent inside a ledger.

Storage scope: ``amount`` is always integer *minor* units (kobo for NGN, cents
for USD). Formatting to major units with a symbol (``₦450.00``) is presentation
(DR-09) and intentionally out of scope here.
"""

from dataclasses import dataclass

from apps.shared.value_objects.currency import Currency
from apps.shared.value_objects.exceptions import CurrencyMismatch, InvalidMoney


@dataclass(frozen=True, slots=True)
class Money:
    """Immutable money: integer minor units + a Currency. Never a float."""

    amount: int
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, int) or isinstance(self.amount, bool):
            raise InvalidMoney(
                f"Money amount must be an int (integer minor units), got {self.amount!r}."
            )
        if not isinstance(self.currency, Currency):
            raise InvalidMoney(
                f"Money currency must be a Currency value object, got {self.currency!r}."
            )

    def __str__(self) -> str:
        # Raw minor units + code. Debugging output — NOT a formatted price (DR-09).
        return f"{self.amount} {self.currency.code}"

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatch(self.currency, other.currency)

    def __add__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __radd__(self, other: object) -> "Money":
        # Python's sum() starts from the int 0; this makes sum([m1, m2]) work.
        if other == 0:
            return self
        return NotImplemented

    def __sub__(self, other: object) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, other: object) -> "Money":
        # A whole number only — a float multiplier would smuggle floats back in.
        if not isinstance(other, int) or isinstance(other, bool):
            return NotImplemented
        return Money(self.amount * other, self.currency)

    def __rmul__(self, other: object) -> "Money":
        return self.__mul__(other)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)
