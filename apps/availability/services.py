"""Availability & Inventory Engines (M7).

Authoritative references:
- SDD S11.1 (Availability: "is it sellable, and how many units remain?")
  and S11.2 (Inventory: "consume / release capacity by room-type, per
  night, per channel.")
- DDS S6+7 — Availability & Inventory (merged table set, D2)
- Implementation roadmap M7

``AvailabilityService`` owns capacity truth (horizon init + reads).
``InventoryService`` owns capacity mutation (hold/sell/convert/release) and
is deliberately Reservation-agnostic — M8 (Reservation) is not built yet;
``hold()``/``convert_hold_to_sold()`` are the raw primitives it will call,
and ``sell()`` is the direct-consumption path for a walk-in/front-desk sale
that skips the hold step entirely. Both call paths share ONE repository
(``AvailabilitySlotRepository``) so the anti-oversell guarantee is identical
regardless of which path a future caller uses.
"""

from datetime import date, timedelta

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from apps.availability.models import AvailabilitySlot, Channel
from apps.availability.partitioning import reserve_slot_ids
from apps.availability.repository import AvailabilitySlotRepository
from apps.shared.services.idempotency import IdempotencyService
from apps.shared.value_objects import DateRange


class AvailabilityService:
    """Horizon initialization + sellability reads (SDD S11.1)."""

    @staticmethod
    def initialize_horizon(
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        total_units: int,
        channel: str = Channel.DIRECT,
        start_date: date | None = None,
        horizon_days: int | None = None,
    ) -> int:
        """Open sellable capacity for [start_date, start_date + horizon_days).

        ``total_units`` is an EXPLICIT parameter — Availability owns sellable
        room-type capacity, never derived from ``Room.objects.count()``
        (physical rooms are Allocation's concern at check-in, SDD S11.6; a
        room-type's sellable capacity is a commercial decision that may
        differ from the physical room count entirely). ``horizon_days``
        defaults to ``settings.AVAILABILITY_HORIZON_DAYS`` (a config value,
        not a hard-coded constant).

        Idempotent per date: a date that already has a slot is left
        untouched (its counters are not reset), so calling this again to
        extend the horizon forward is always safe. Returns the number of
        NEW slots created.
        """
        start = start_date or timezone.now().date()
        horizon = horizon_days if horizon_days is not None else settings.AVAILABILITY_HORIZON_DAYS
        wanted_dates = [start + timedelta(days=offset) for offset in range(horizon)]

        existing_dates = set(
            AvailabilitySlot.objects.filter(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_date__in=wanted_dates,
            ).values_list("business_date", flat=True)
        )
        missing_dates = [d for d in wanted_dates if d not in existing_dates]
        if not missing_dates:
            return 0

        ids = reserve_slot_ids(len(missing_dates))
        rows = [
            AvailabilitySlot(
                id=slot_id,
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_date=business_date,
                total_units=total_units,
            )
            for slot_id, business_date in zip(ids, missing_dates, strict=False)
        ]
        AvailabilitySlot.objects.bulk_create(rows)
        return len(rows)


class AvailabilityQuery:
    """Read-only selector over ``availability_slot`` (the search/quote hot path)."""

    @staticmethod
    def remaining_for_range(
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        date_range: DateRange,
        channel: str = Channel.DIRECT,
    ) -> dict[date, int]:
        """``{business_date: remaining}`` for every night in ``date_range``
        (half-open: the departure date itself is excluded — matches
        ``DateRange``'s own convention). Missing (uninitialized) dates are
        simply absent from the result — treat an absent key as "not
        sellable", the same rule the repository enforces on write."""
        rows = AvailabilitySlot.objects.filter(
            tenant_id=tenant_id,
            property_id=property_id,
            room_type_id=room_type_id,
            channel=channel,
            business_date__gte=date_range.start,
            business_date__lt=date_range.end,
        ).values_list("business_date", "remaining")
        return dict(rows)

    @staticmethod
    def is_sellable(
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        date_range: DateRange,
        quantity: int,
        channel: str = Channel.DIRECT,
    ) -> bool:
        """True iff EVERY night in ``date_range`` is initialized and has at
        least ``quantity`` remaining — a read-only preview of what
        ``InventoryService`` would enforce on write. This is a
        performance-only convenience (no lock is held); the repository's
        locked check at write time is the actual truth (DR-05)."""
        nights = [date_range.start + timedelta(days=n) for n in range(date_range.days)]
        remaining = AvailabilityQuery.remaining_for_range(
            tenant_id=tenant_id,
            property_id=property_id,
            room_type_id=room_type_id,
            date_range=date_range,
            channel=channel,
        )
        return all(remaining.get(night, 0) >= quantity for night in nights)

    @staticmethod
    def max_business_date(
        *, tenant_id: int, property_id: int, room_type_id: int, channel: str = Channel.DIRECT
    ) -> date | None:
        """The furthest-out initialized date — how far the sellable horizon
        currently reaches for this room type."""
        return AvailabilitySlot.objects.filter(
            tenant_id=tenant_id,
            property_id=property_id,
            room_type_id=room_type_id,
            channel=channel,
        ).aggregate(m=Max("business_date"))["m"]


class InventoryService:
    """Capacity mutation (SDD S11.2). Reservation-agnostic (M7 scope): no
    reservation/hold-TTL concept lives here — those are M8's."""

    @staticmethod
    def _nights(date_range: DateRange) -> list[date]:
        return [date_range.start + timedelta(days=n) for n in range(date_range.days)]

    @classmethod
    def sell(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        date_range: DateRange,
        quantity: int,
        idempotency_key: str,
        channel: str = Channel.DIRECT,
    ) -> dict:
        """Direct consumption — no hold step (e.g. a front-desk walk-in
        sale). Increments ``sold`` across the whole window, all-or-nothing,
        under the repository's pessimistic lock. Idempotent per
        ``idempotency_key`` (``IdempotencyService`` — M7 reuses the existing
        mechanism rather than inventing another one)."""
        nights = cls._nights(date_range)
        request_payload = {
            "op": "sell",
            "property_id": property_id,
            "room_type_id": room_type_id,
            "channel": channel,
            "start": date_range.start.isoformat(),
            "end": date_range.end.isoformat(),
            "quantity": quantity,
        }

        def _execute() -> dict:
            AvailabilitySlotRepository.consume_window(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_dates=nights,
                quantity=quantity,
                field="sold",
            )
            return {"consumed": True, "nights": len(nights), "field": "sold"}

        return IdempotencyService(tenant_id=tenant_id, scope="inventory.sell").run(
            idempotency_key, request_payload, execute=_execute
        )

    @classmethod
    def hold(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        date_range: DateRange,
        quantity: int,
        idempotency_key: str,
        channel: str = Channel.DIRECT,
    ) -> dict:
        """Reserve (not sell) capacity — increments ``reserved``. The raw
        primitive a future Reservation Engine (M8) calls when it creates a
        hold; carries no TTL concept itself (that is M8's Redis+Celery
        seam)."""
        nights = cls._nights(date_range)
        request_payload = {
            "op": "hold",
            "property_id": property_id,
            "room_type_id": room_type_id,
            "channel": channel,
            "start": date_range.start.isoformat(),
            "end": date_range.end.isoformat(),
            "quantity": quantity,
        }

        def _execute() -> dict:
            AvailabilitySlotRepository.consume_window(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_dates=nights,
                quantity=quantity,
                field="reserved",
            )
            return {"held": True, "nights": len(nights), "field": "reserved"}

        return IdempotencyService(tenant_id=tenant_id, scope="inventory.hold").run(
            idempotency_key, request_payload, execute=_execute
        )

    @classmethod
    def convert_hold_to_sold(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        date_range: DateRange,
        quantity: int,
        idempotency_key: str,
        channel: str = Channel.DIRECT,
    ) -> dict:
        """Reserved -> sold conversion (e.g. a reservation's hold converts
        on successful payment). Moves ``quantity`` from ``reserved`` to
        ``sold`` across the whole window, all-or-nothing."""
        nights = cls._nights(date_range)
        request_payload = {
            "op": "convert_hold_to_sold",
            "property_id": property_id,
            "room_type_id": room_type_id,
            "channel": channel,
            "start": date_range.start.isoformat(),
            "end": date_range.end.isoformat(),
            "quantity": quantity,
        }

        def _execute() -> dict:
            AvailabilitySlotRepository.convert_reserved_to_sold(
                tenant_id=tenant_id,
                property_id=property_id,
                room_type_id=room_type_id,
                channel=channel,
                business_dates=nights,
                quantity=quantity,
            )
            return {"converted": True, "nights": len(nights)}

        return IdempotencyService(tenant_id=tenant_id, scope="inventory.convert_hold_to_sold").run(
            idempotency_key, request_payload, execute=_execute
        )

    @classmethod
    def release_hold(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        date_range: DateRange,
        quantity: int,
        channel: str = Channel.DIRECT,
    ) -> None:
        """Release previously-held (``reserved``) capacity. Idempotent — a
        no-op past the point where nothing remains to release."""
        AvailabilitySlotRepository.release_window(
            tenant_id=tenant_id,
            property_id=property_id,
            room_type_id=room_type_id,
            channel=channel,
            business_dates=cls._nights(date_range),
            quantity=quantity,
            field="reserved",
        )

    @classmethod
    def release_sold(
        cls,
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        date_range: DateRange,
        quantity: int,
        channel: str = Channel.DIRECT,
    ) -> None:
        """Release previously-sold capacity (e.g. a cancellation). Idempotent
        — a no-op past the point where nothing remains to release."""
        AvailabilitySlotRepository.release_window(
            tenant_id=tenant_id,
            property_id=property_id,
            room_type_id=room_type_id,
            channel=channel,
            business_dates=cls._nights(date_range),
            quantity=quantity,
            field="sold",
        )

    @staticmethod
    def adjust_out_of_service(
        *,
        tenant_id: int,
        property_id: int,
        room_type_id: int,
        start_date: date,
        end_date: date,
        delta: int,
        channel: str = Channel.DIRECT,
    ) -> int:
        """+/- ``delta`` on ``out_of_service`` across [start_date, end_date)
        — the primitive ``RoomStateProjector`` calls when a room enters or
        leaves OOO/OOS."""
        return AvailabilitySlotRepository.adjust_out_of_service_window(
            tenant_id=tenant_id,
            property_id=property_id,
            room_type_id=room_type_id,
            channel=channel,
            start_date=start_date,
            end_date=end_date,
            delta=delta,
        )
