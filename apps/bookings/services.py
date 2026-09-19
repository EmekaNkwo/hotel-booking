"""Booking Engine (M9, SDD S10.2, DDS S10).

Authoritative references:
- SDD S10.2 (Reservation -> Booking lifecycle semantics), S9.3 (state machine)
- DDS S10 — Booking (schema + invariants), A.7 (T1: the atomic confirm transaction)
- DMS S10 — Booking aggregate, invariants #4/#5/#6/#8
- Implementation roadmap M9

``BookingService.confirm()`` is the ONLY entry point. It composes
``ReservationService.convert()`` (M8) — never reimplementing the
``Awaiting_Payment`` guard, never calling ``InventoryService``/touching
``AvailabilitySlot`` directly, never calling ``GuestService``/
``PricingService``/``PolicyService``. Every snapshot on the ``Booking`` is a
verbatim copy of what M8 already pinned on the ``Reservation``.
"""

import secrets

from apps.bookings.models import Booking, BookingLine, BookingStatus
from apps.reservations.services import ReservationService
from apps.shared.services.idempotency import IdempotencyService
from apps.shared.workflows.runner import WorkflowRunner


def _generate_booking_ref() -> str:
    """Same shape as ``reservations._generate_reservation_ref`` — an
    app-specific, short, opaque reference; not shared to ``apps.shared``
    since a second near-identical four-line function doesn't yet justify
    the abstraction (one extra consumer would)."""
    return secrets.token_hex(4).upper()


def _guest_snapshot(guest_profile) -> dict:
    """A point-in-time copy of the identity fields a booking needs to
    remember, independent of later profile merges (DMS invariant #8)."""
    if guest_profile is None:
        return {}
    return {
        "name": guest_profile.name,
        "email": guest_profile.primary_email,
        "phone": guest_profile.primary_phone,
    }


class BookingService:
    """The booking confirmation flow: reservation -> committed booking."""

    @classmethod
    def confirm(cls, *, tenant_id: int, reservation_id: int, idempotency_key: str) -> Booking:
        """Convert the reservation and create the committed Booking — ONE
        atomic transaction (``IdempotencyService`` supplies the outer
        transaction boundary; nothing here opens a second one, matching the
        ``ReservationService.reserve()`` discipline from M8).

        ``tenant_id`` is caller-supplied (mirrors ``ReservationService.cancel()``
        and ``InventoryService``'s explicit-tenant-id convention) rather than
        derived with an extra lookup.

        Any failure — the ``Awaiting_Payment`` guard inside
        ``ReservationService.convert()``, an inventory conversion error, or
        anything after — rolls back the WHOLE transaction: the reservation's
        conversion, the inventory sold-conversion, and every ``Booking``/
        ``BookingLine`` row created so far.
        """
        request_payload = {"reservation_id": reservation_id}

        def _execute() -> dict:
            reservation = ReservationService.convert(reservation_id, tenant_id=tenant_id)

            reservation_lines = list(reservation.lines.all())
            arrival_date = min(line.arrival_date for line in reservation_lines)
            departure_date = max(line.departure_date for line in reservation_lines)

            booking = Booking.objects.create(
                tenant=reservation.tenant,
                property=reservation.property,
                reservation=reservation,
                guest_profile=reservation.guest_profile,
                booking_ref=_generate_booking_ref(),
                aggregate_status=BookingStatus.PENDING_PAYMENT,
                currency=reservation.price_snapshot["currency"],
                total_minor_units=reservation.price_snapshot["total_minor_units"],
                arrival_date=arrival_date,
                departure_date=departure_date,
                price_snapshot=reservation.price_snapshot,
                policy_snapshot=reservation.policy_snapshot,
                guest_snapshot=_guest_snapshot(reservation.guest_profile),
            )

            line_no = 0
            booking_lines = []
            for reservation_line in reservation_lines:
                for _ in range(reservation_line.quantity):
                    line_no += 1
                    booking_lines.append(
                        BookingLine(
                            booking=booking,
                            line_no=line_no,
                            room_type=reservation_line.room_type,
                            room=None,
                            arrival_date=reservation_line.arrival_date,
                            departure_date=reservation_line.departure_date,
                            status=BookingStatus.CONFIRMED,
                            price_snapshot=reservation_line.price_snapshot,
                        )
                    )
            BookingLine.objects.bulk_create(booking_lines)

            WorkflowRunner(booking, field="aggregate_status").run(
                "confirm", reason="reservation converted; inventory sold"
            )
            return {"booking_id": booking.id}

        response = IdempotencyService(tenant_id=tenant_id, scope="booking.confirm").run(
            idempotency_key, request_payload, execute=_execute
        )
        return Booking.objects.get(pk=response["booking_id"])


class BookingQuery:
    """Read-only selectors over ``booking``/``booking_line`` (mirrors
    ``ReservationQuery``/``RoomQuery``)."""

    @staticmethod
    def by_booking_ref(tenant, booking_ref: str) -> Booking | None:
        return Booking.objects.filter(tenant=tenant, booking_ref=booking_ref).first()

    @staticmethod
    def by_guest(guest_profile):
        return Booking.objects.filter(guest_profile=guest_profile).order_by("-created_at")

    @staticmethod
    def by_reservation(reservation) -> Booking | None:
        return Booking.objects.filter(reservation=reservation).first()

    @staticmethod
    def arrivals_for_property(property, arrival_date):
        return BookingLine.objects.filter(
            booking__property=property,
            arrival_date=arrival_date,
            status__in=[BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN],
        ).select_related("booking", "room_type")
