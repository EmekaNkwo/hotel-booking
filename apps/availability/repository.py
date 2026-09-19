"""AvailabilitySlotRepository — the anti-oversell repository capability (M7, R1, DR-05, E6).

This is one of the few places the project applies the repository pattern for
real (E6): the availability invariant races every concurrent booking attempt
against every other, so the write path needs a single, disciplined place that
always locks before it reads-to-decide, and always writes inside that lock —
never an optimistic retry loop (architecture-philosophy S1.5: "using
transactions to compensate for missing validation" is the anti-pattern this
repository exists to avoid; the guard runs BEFORE any write, under the lock
that makes the guard's result still true at write time).

Every method:
1. ``SELECT ... FOR UPDATE`` the full affected window, ``ORDER BY
   business_date`` — deterministic lock ordering (D9) so two callers whose
   windows overlap always acquire row locks in the same order and can only
   ever deadlock-free block on each other, never deadlock.
2. Checks the invariant against the LOCKED values (guaranteed fresh — no
   other writer can have changed them since the lock was acquired).
3. Writes every affected row inside the SAME transaction, all-or-nothing —
   a multi-night consume either fully succeeds or touches nothing.
"""

from datetime import date

from django.db import transaction
from django.db.models import F

from apps.availability.exceptions import InsufficientAvailability
from apps.availability.models import AvailabilitySlot


class AvailabilitySlotRepository:
    """Locking + conditional-write primitives over ``availability_slot``."""

    @staticmethod
    def lock_window(
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        channel: str,
        business_dates: list[date],
    ) -> dict[date, AvailabilitySlot]:
        """Lock every slot in ``business_dates``; require ALL to exist.

        An uninitialized date has no row and is therefore not sellable at
        all (never "infinite") — this is deliberate: capacity must be
        opened explicitly via ``AvailabilityService.initialize_horizon``
        before it can be consumed (SDD S11.2).
        """
        rows = list(
            AvailabilitySlot.objects.select_for_update()
            .filter(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_date__in=business_dates,
            )
            .order_by("business_date")
        )
        by_date = {row.business_date: row for row in rows}
        missing = sorted(d for d in business_dates if d not in by_date)
        if missing:
            raise InsufficientAvailability(
                f"no availability slot initialized for {missing!r} "
                f"(room_type={room_type_id}, channel={channel})"
            )
        return by_date

    @classmethod
    def consume_window(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        channel: str,
        business_dates: list[date],
        quantity: int,
        field: str,
    ) -> None:
        """Lock the window, then increment ``field`` by ``quantity`` on every
        night, all-or-nothing. ``field`` is ``"sold"`` or ``"reserved"``."""
        with transaction.atomic():
            locked = cls.lock_window(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_dates=business_dates,
            )
            shortfalls = sorted(d for d, row in locked.items() if row.remaining < quantity)
            if shortfalls:
                raise InsufficientAvailability(
                    f"insufficient remaining capacity on {shortfalls!r} for "
                    f"quantity={quantity} (room_type={room_type_id}, channel={channel})"
                )
            for d in business_dates:
                row = locked[d]
                AvailabilitySlot.objects.filter(business_date=row.business_date, id=row.id).update(
                    **{field: F(field) + quantity}
                )

    @classmethod
    def release_window(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        channel: str,
        business_dates: list[date],
        quantity: int,
        field: str,
    ) -> None:
        """Lock the window, then decrement ``field`` by ``quantity`` on every
        night, capped at the currently-held amount per night — releasing
        more than is held (or releasing an already-fully-released window) is
        a safe no-op rather than an error, which is what makes release
        idempotent (M7 review gate)."""
        with transaction.atomic():
            locked = cls.lock_window(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_dates=business_dates,
            )
            for d in business_dates:
                row = locked[d]
                actual = min(quantity, getattr(row, field))
                if actual <= 0:
                    continue
                AvailabilitySlot.objects.filter(business_date=row.business_date, id=row.id).update(
                    **{field: F(field) - actual}
                )

    @classmethod
    def convert_reserved_to_sold(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        channel: str,
        business_dates: list[date],
        quantity: int,
    ) -> None:
        """Lock the window, then move ``quantity`` from ``reserved`` to
        ``sold`` on every night, all-or-nothing."""
        with transaction.atomic():
            locked = cls.lock_window(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_dates=business_dates,
            )
            shortfalls = sorted(d for d, row in locked.items() if row.reserved < quantity)
            if shortfalls:
                raise InsufficientAvailability(
                    f"insufficient reserved capacity to convert on {shortfalls!r} for "
                    f"quantity={quantity} (room_type={room_type_id}, channel={channel})"
                )
            for d in business_dates:
                row = locked[d]
                AvailabilitySlot.objects.filter(business_date=row.business_date, id=row.id).update(
                    reserved=F("reserved") - quantity, sold=F("sold") + quantity
                )

    @staticmethod
    def adjust_out_of_service_window(
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        channel: str,
        start_date: date,
        end_date: date,
        delta: int,
    ) -> int:
        """+/- ``delta`` on ``out_of_service`` for every INITIALIZED slot in
        [start_date, end_date). Silently skips dates with no slot row yet —
        an uninitialized date has no sellable capacity to flag. All affected
        rows are locked and updated in ONE transaction (RoomStateProjector,
        M7 scope item 11): if any night's update would violate the
        non-negative/within-total invariant, the whole adjustment rolls back
        so the caller can retry the whole event rather than leave a
        half-applied delta.
        """
        with transaction.atomic():
            rows = list(
                AvailabilitySlot.objects.select_for_update()
                .filter(
                    tenant_id=tenant_id,
                    property_id=property_id,
                    room_type_id=room_type_id,
                    channel=channel,
                    business_date__gte=start_date,
                    business_date__lt=end_date,
                )
                .order_by("business_date")
            )
            for row in rows:
                AvailabilitySlot.objects.filter(business_date=row.business_date, id=row.id).update(
                    out_of_service=F("out_of_service") + delta
                )
            return len(rows)
