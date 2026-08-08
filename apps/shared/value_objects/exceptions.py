"""The single exception family for every value object rejection.

Consumers catch ``ValueObjectError`` once to handle "any value object rejected a
value"; each specific object raises its own subclass, carrying context where it
helps debugging.

This module never imports the value objects at runtime, so a value object may
safely import its exceptions without creating an import cycle. Type checkers
resolve the annotations below via the ``TYPE_CHECKING`` import.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import-time only, never executed
    from apps.shared.value_objects.currency import Currency


class ValueObjectError(ValueError):
    """Base class for every value object rejection.

    Also a ``ValueError`` (Python's canonical "a value was invalid" signal) so
    generic code that catches ``ValueError`` keeps working without knowing us.
    """


class InvalidCurrency(ValueObjectError):
    """A value is not a valid ISO-4217 currency code."""


class InvalidMoney(ValueObjectError):
    """A value cannot be built into a Money (non-int amount, or a non-Currency currency)."""


class InvalidDateRange(ValueObjectError):
    """A value cannot form a valid DateRange (non-date bounds, or end not after start)."""


class InvalidStayPeriod(ValueObjectError):
    """A value cannot form a valid StayPeriod (non-date bounds, or departure not after arrival)."""


class CurrencyMismatch(ValueObjectError):
    """Arithmetic between two Moneys of different currencies.

    Carries both currencies so a traceback names the exact offending pair.
    """

    def __init__(self, left: "Currency", right: "Currency") -> None:
        self.left = left
        self.right = right
        super().__init__(f"Cannot combine currencies: {left.code} and {right.code}.")
