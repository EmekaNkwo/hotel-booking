"""Exceptions for the Shared Kernel's Django (persistence) layer.

These sit alongside the framework-free value-object exceptions
(apps/shared/value_objects/exceptions.py) but are deliberately separate: the
VO exceptions guard in-memory value construction, while these guard entity
persistence. Both are catchable independently of each other.
"""


class ConcurrencyError(Exception):
    """A versioned save() found the row changed since it was loaded.

    Raised when ``UPDATE ... WHERE id = ? AND version = <as-loaded>`` matched
    zero rows — another writer committed first. The caller should reload the
    row and re-apply its change (or surface "someone else changed this").
    """
