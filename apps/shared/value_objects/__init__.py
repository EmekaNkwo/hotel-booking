"""Shared Kernel value objects — the cross-context vocabulary (DR-09).

Public surface: import from this package root, never from internal modules.
E.g. ``from apps.shared.value_objects import Money``. Internal module layout may
be reorganized without touching a single consumer import.
"""

from apps.shared.value_objects.currency import Currency
from apps.shared.value_objects.exceptions import (
    CurrencyMismatch,
    InvalidCurrency,
    InvalidMoney,
    ValueObjectError,
)
from apps.shared.value_objects.money import Money

__all__ = [
    "Currency",
    "CurrencyMismatch",
    "InvalidCurrency",
    "InvalidMoney",
    "Money",
    "ValueObjectError",
]
