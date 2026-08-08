"""Typed ids — int subclasses that carry meaning, as value objects.

The bug this prevents: ``reserve(tenant, property)`` receiving swapped
arguments — both are ``int 5``, and bare ints give the type checker nothing to
catch. ``TenantId(5)`` and ``PropertyId(5)`` are distinct *types*, so the swap
becomes a type error instead of a silent cross-tenant booking.

Typed ids are int subclasses (matching the DDS BIGINT PKs): drop-in for Django
FK fields, comparable and hashable by value, immutable by nature. The safety is
at the type-checker and readability level — ``TenantId(5) == PropertyId(5)`` is
``True`` at runtime because both are 5. That limitation is deliberate: we
accept int semantics rather than break them. The *type* carries meaning; the
owning context carries the rules (existence, tenancy, referential integrity).
"""

from apps.shared.value_objects.exceptions import InvalidId


class EntityId(int):
    """Base for strongly-typed identifier value objects.

    A non-negative int that reads as a specific domain id. Subclassing is the
    only mechanism: ``class RoomTypeId(EntityId): ...`` is one line per id.
    """

    def __new__(cls, value: int) -> "EntityId":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidId(f"{cls.__name__} must be a non-negative int, got {value!r}.")
        if value < 0:
            raise InvalidId(f"{cls.__name__} must be non-negative, got {value!r}.")
        return super().__new__(cls, value)


class TenantId(EntityId):
    """Identifier of a tenant (M2)."""


class UserId(EntityId):
    """Identifier of a platform user account (M2)."""


class PropertyId(EntityId):
    """Identifier of a property (M3)."""


class RoomTypeId(EntityId):
    """Identifier of a room type (M3)."""


class GuestId(EntityId):
    """Identifier of a guest profile (M5)."""
