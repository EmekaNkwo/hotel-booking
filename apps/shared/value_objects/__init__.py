"""Shared Kernel value objects — the cross-context vocabulary (DR-09).

Public surface: import from this package root, never from internal modules.
E.g. ``from apps.shared.value_objects import Money``. Internal module layout may
be reorganized without touching a single consumer import.
"""

from apps.shared.value_objects.currency import Currency
from apps.shared.value_objects.date_range import DateRange
from apps.shared.value_objects.exceptions import (
    CurrencyMismatch,
    InvalidCurrency,
    InvalidDateRange,
    InvalidMoney,
    InvalidStayPeriod,
    ValueObjectError,
)
from apps.shared.value_objects.money import Money
from apps.shared.value_objects.stay_period import StayPeriod

__all__ = [
    "Currency",
    "CurrencyMismatch",
    "DateRange",
    "InvalidCurrency",
    "InvalidDateRange",
    "InvalidMoney",
    "InvalidStayPeriod",
    "Money",
    "StayPeriod",
    "ValueObjectError",
]
