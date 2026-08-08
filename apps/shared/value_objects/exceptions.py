"""The single exception family for every value object rejection.

Consumers catch ``ValueObjectError`` once to handle "any value object rejected a
value"; each specific object raises its own subclass, carrying context where it
helps debugging.
"""


class ValueObjectError(ValueError):
    """Base class for every value object rejection.

    Also a ``ValueError`` (Python's canonical "a value was invalid" signal) so
    generic code that catches ``ValueError`` keeps working without knowing us.
    """


class InvalidCurrency(ValueObjectError):
    """A value is not a valid ISO-4217 currency code."""
