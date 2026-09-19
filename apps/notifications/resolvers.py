"""NotificationRecipientResolver (M13, ruling S3).

Producer events (``reservation.*``, ``booking.confirmed``, ``room.allocated``)
do not carry ``guest_profile_id`` in their outbox payload, and M8/M9/M11 are
not modified merely to add it. This resolver is the ONE place that bridges
a ``DomainEvent``'s ``(aggregate_type, aggregate_id)`` back to a guest and
an immutable rendering context — read-only, never mutating any producer's
tables (Reservation, Booking, Allocation, Guest).
"""

from dataclasses import dataclass

from apps.shared.models import DomainEvent


@dataclass(frozen=True, slots=True)
class ResolvedRecipient:
    guest_profile_id: int
    tenant_id: int
    context: dict


def _guest_display_name(guest_profile) -> str:
    name = guest_profile.name or {}
    return name.get("display_name") or name.get("given_name") or "Guest"


def _resolve_reservation_event(event: DomainEvent) -> ResolvedRecipient | None:
    from apps.reservations.models import Reservation

    reservation = (
        Reservation.objects.filter(pk=event.aggregate_id).select_related("guest_profile").first()
    )
    if reservation is None or reservation.guest_profile_id is None:
        return None
    lines = list(reservation.lines.all())
    arrival = min((line.arrival_date for line in lines), default=None)
    departure = max((line.departure_date for line in lines), default=None)
    return ResolvedRecipient(
        guest_profile_id=reservation.guest_profile_id,
        tenant_id=reservation.tenant_id,
        context={
            "guest_name": _guest_display_name(reservation.guest_profile),
            "reservation_ref": reservation.reservation_ref,
            "arrival_date": arrival.isoformat() if arrival else None,
            "departure_date": departure.isoformat() if departure else None,
        },
    )


def _resolve_booking_event(event: DomainEvent) -> ResolvedRecipient | None:
    from apps.bookings.models import Booking

    booking = Booking.objects.filter(pk=event.aggregate_id).select_related("guest_profile").first()
    if booking is None or booking.guest_profile_id is None:
        return None
    return ResolvedRecipient(
        guest_profile_id=booking.guest_profile_id,
        tenant_id=booking.tenant_id,
        context={
            "guest_name": _guest_display_name(booking.guest_profile),
            "booking_ref": booking.booking_ref,
            "arrival_date": booking.arrival_date.isoformat(),
            "departure_date": booking.departure_date.isoformat(),
            "total_minor_units": booking.total_minor_units,
            "currency": booking.currency,
        },
    )


def _resolve_allocation_event(event: DomainEvent) -> ResolvedRecipient | None:
    from apps.allocation.models import AllocationRecord

    record = (
        AllocationRecord.objects.filter(pk=event.aggregate_id)
        .select_related("room", "booking_line__booking__guest_profile")
        .first()
    )
    if record is None:
        return None
    booking = record.booking_line.booking
    if booking.guest_profile_id is None:
        return None
    return ResolvedRecipient(
        guest_profile_id=booking.guest_profile_id,
        tenant_id=record.tenant_id,
        context={
            "guest_name": _guest_display_name(booking.guest_profile),
            "booking_ref": booking.booking_ref,
            "room_code": record.room.code,
            "arrival_date": record.booking_line.arrival_date.isoformat(),
            "departure_date": record.booking_line.departure_date.isoformat(),
        },
    )


_HANDLERS = {
    "reservation.created": _resolve_reservation_event,
    "reservation.expired": _resolve_reservation_event,
    "reservation.converted": _resolve_reservation_event,
    "booking.confirmed": _resolve_booking_event,
    "room.allocated": _resolve_allocation_event,
}

NOTIFIABLE_EVENT_TYPES = tuple(_HANDLERS)


class NotificationRecipientResolver:
    """Read-only resolution from a ``DomainEvent`` to its guest recipient +
    rendering context. Never mutates Reservation/Booking/Allocation/Guest."""

    @staticmethod
    def resolve(event: DomainEvent) -> ResolvedRecipient | None:
        handler = _HANDLERS.get(event.event_type)
        if handler is None:
            return None
        return handler(event)
