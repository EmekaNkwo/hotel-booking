"""Shared Kernel value objects — the cross-context vocabulary (DR-09).

Public surface: import from this package root, never from internal modules.
E.g. ``from apps.shared.value_objects import Money``. Internal module layout may
be reorganized without touching a single consumer import.
"""

from apps.shared.value_objects.address import Address
from apps.shared.value_objects.currency import Currency
from apps.shared.value_objects.date_range import DateRange
from apps.shared.value_objects.email import Email
from apps.shared.value_objects.exceptions import (
    CurrencyMismatch,
    InvalidAddress,
    InvalidCurrency,
    InvalidDateRange,
    InvalidEmail,
    InvalidGeoLocation,
    InvalidGuestCount,
    InvalidGuestName,
    InvalidId,
    InvalidMoney,
    InvalidPhoneNumber,
    InvalidPriceBreakdown,
    InvalidStayPeriod,
    InvalidTimeZone,
    ValueObjectError,
)
from apps.shared.value_objects.geo_location import GeoLocation
from apps.shared.value_objects.guest_count import GuestCount
from apps.shared.value_objects.guest_name import GuestName
from apps.shared.value_objects.money import Money
from apps.shared.value_objects.phone_number import PhoneNumber
from apps.shared.value_objects.price_breakdown import LineItem, NightlyPrice, PriceBreakdown
from apps.shared.value_objects.stay_period import StayPeriod
from apps.shared.value_objects.time_zone_id import TimeZoneId
from apps.shared.value_objects.typed_ids import (
    EntityId,
    GuestId,
    PropertyId,
    RoomTypeId,
    TenantId,
    UserId,
)

__all__ = [
    "Address",
    "Currency",
    "CurrencyMismatch",
    "DateRange",
    "Email",
    "EntityId",
    "GeoLocation",
    "GuestCount",
    "GuestId",
    "GuestName",
    "InvalidAddress",
    "InvalidCurrency",
    "InvalidDateRange",
    "InvalidEmail",
    "InvalidGeoLocation",
    "InvalidGuestCount",
    "InvalidGuestName",
    "InvalidId",
    "InvalidMoney",
    "InvalidPhoneNumber",
    "InvalidPriceBreakdown",
    "InvalidStayPeriod",
    "InvalidTimeZone",
    "LineItem",
    "Money",
    "NightlyPrice",
    "PhoneNumber",
    "PriceBreakdown",
    "PropertyId",
    "RoomTypeId",
    "StayPeriod",
    "TenantId",
    "TimeZoneId",
    "UserId",
    "ValueObjectError",
]
