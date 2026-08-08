"""Shared Kernel value objects — the cross-context vocabulary (DR-09).

Public surface: import from this package root, never from internal modules.
E.g. ``from apps.shared.value_objects import Money``. Internal module layout may
be reorganized without touching a single consumer import.
"""

from apps.shared.value_objects.currency import Currency
from apps.shared.value_objects.date_range import DateRange
from apps.shared.value_objects.email import Email
from apps.shared.value_objects.exceptions import (
    CurrencyMismatch,
    InvalidCurrency,
    InvalidDateRange,
    InvalidEmail,
    InvalidGuestCount,
    InvalidMoney,
    InvalidPhoneNumber,
    InvalidStayPeriod,
    ValueObjectError,
)
from apps.shared.value_objects.guest_count import GuestCount
from apps.shared.value_objects.money import Money
from apps.shared.value_objects.phone_number import PhoneNumber
from apps.shared.value_objects.stay_period import StayPeriod

__all__ = [
    "Currency",
    "CurrencyMismatch",
    "DateRange",
    "Email",
    "GuestCount",
    "InvalidCurrency",
    "InvalidDateRange",
    "InvalidEmail",
    "InvalidGuestCount",
    "InvalidMoney",
    "InvalidPhoneNumber",
    "InvalidStayPeriod",
    "Money",
    "PhoneNumber",
    "StayPeriod",
    "ValueObjectError",
]
