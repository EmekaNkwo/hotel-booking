"""Shared Kernel value objects — the cross-context vocabulary (DR-09).

Public surface: import from this package root, never from internal modules.
E.g. ``from apps.shared.value_objects import Currency``. Internal module layout
may be reorganized without touching a single consumer import.
"""

from apps.shared.value_objects.currency import Currency
from apps.shared.value_objects.exceptions import InvalidCurrency, ValueObjectError

__all__ = ["Currency", "InvalidCurrency", "ValueObjectError"]
