"""Reservation Engine (M8, SDD S11.4, DDS S9).

Authoritative references:
- SDD S10.1 (Reservation -> Booking flow), S11.4 (Reservation Engine), S9.3
  (state machine)
- DDS S9 — Reservation (schema + invariants)
- Implementation roadmap M8

``ReservationService`` is the ONLY entry point for the reservation
lifecycle. It composes existing capabilities and duplicates none of their
logic (SDD S6.3): it asks ``GuestService`` for identity, ``PricingService``
for price, ``PolicyService`` for the deposit answer, and
``InventoryService`` for capacity — never touching ``AvailabilitySlot``,
computing a price, or interpreting ``Policy.rules`` itself.
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.availability.models import Channel
from apps.availability.services import InventoryService
from apps.guests.services import GuestService
from apps.policies.models import PolicyType
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.reservations.models import Reservation, ReservationLine, ReservationStatus
from apps.rooms.models import RoomType
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.services.idempotency import IdempotencyService
from apps.shared.value_objects import GuestCount, GuestName, StayPeriod
from apps.shared.workflows.runner import WorkflowRunner

_UNSETTLED_STATUSES = (ReservationStatus.HELD, ReservationStatus.AWAITING_PAYMENT)


@dataclass(frozen=True, slots=True)
class ReservationLineRequest:
    """One requested room-type-line — the input shape ``reserve()`` accepts.

    Not a Shared Kernel value object (it composes reservation-specific
    inputs, not cross-domain vocabulary) and not persisted directly — it is
    consumed inside ``reserve()`` to produce a ``ReservationLine`` row.
    """

    room_type_id: int
    stay_period: StayPeriod
    guest_count: GuestCount
    quantity: int = 1

    def to_payload(self) -> dict:
        """The JSON-serializable form used in the idempotency fingerprint."""
        return {
            "room_type_id": self.room_type_id,
            "arrival": self.stay_period.arrival.isoformat(),
            "departure": self.stay_period.departure.isoformat(),
            "adults": self.guest_count.adults,
            "children": self.guest_count.children,
            "infants": self.guest_count.infants,
            "quantity": self.quantity,
        }


def _generate_reservation_ref() -> str:
    """A short, opaque, tenant-scoped-unique reference (uniqueness enforced
    by the DB constraint; collision retry is the caller's concern if it ever
    matters at this entropy — 8 base32 chars is ~40 bits)."""
    return secrets.token_hex(4).upper()


class ReservationService:
    """The reservation lifecycle: reserve, expire, cancel, convert."""

    # ------------------------------------------------------------------
    # reserve() — quote + hold, one atomic transaction (DMS S9 invariant #1)
    # ------------------------------------------------------------------

    @classmethod
    def reserve(
        cls,
        *,
        tenant,
        property,
        lines: list[ReservationLineRequest],
        idempotency_key: str,
        guest_email: str | None = None,
        guest_phone: str | None = None,
        guest_name: GuestName | None = None,
        guest_language: str = "",
        hold_minutes: int | None = None,
    ) -> Reservation:
        """Quote every line, pin the deposit policy, create the reservation,
        hold every line's capacity, and transition Draft -> Held — all in
        ONE atomic transaction (``IdempotencyService`` supplies the outer
        transaction; nothing here opens a second one).

        A failed hold (``InsufficientAvailability`` from any line) rolls the
        whole transaction back: no ``Reservation``, no ``ReservationLine``,
        no partial hold survives.
        """
        if not lines:
            raise ValueError("reserve() requires at least one reservation line.")

        request_payload = {
            "property_id": property.id,
            "guest_email": guest_email,
            "guest_phone": guest_phone,
            "lines": [line.to_payload() for line in lines],
        }

        def _execute() -> dict:
            guest = None
            if guest_email or guest_phone:
                guest = GuestService.resolve(
                    tenant,
                    email=guest_email,
                    phone=guest_phone,
                    name=guest_name,
                    language=guest_language,
                )

            quoted = []
            for line in lines:
                room_type = RoomType.objects.get(pk=line.room_type_id, tenant=tenant)
                breakdown = PricingService.price(
                    property, room_type, line.stay_period, line.guest_count
                )
                quoted.append((line, room_type, breakdown))

            earliest_arrival = min(line.stay_period.arrival for line in lines)
            policy, answer = PolicyService.resolve(
                tenant, PolicyType.DEPOSIT, earliest_arrival, property.id
            )
            policy_snapshot = {
                "deposit": {
                    "policy_id": policy.id,
                    "version": policy.version,
                    "answer": {
                        "required": answer.get("required", False),
                        "amount": answer.get("amount"),
                    },
                }
            }

            currency = quoted[0][2].currency.code
            total_minor_units = sum(b.total.amount for _, _, b in quoted)
            price_snapshot = {
                "currency": currency,
                "total_minor_units": total_minor_units,
                "lines": [b.to_dict() for _, _, b in quoted],
            }

            hold_minutes_effective = (
                hold_minutes if hold_minutes is not None else settings.RESERVATION_HOLD_MINUTES
            )
            reservation = Reservation.objects.create(
                tenant=tenant,
                property=property,
                guest_profile=guest,
                reservation_ref=_generate_reservation_ref(),
                status=ReservationStatus.DRAFT,
                channel=Channel.DIRECT,
                hold_expiry_at=timezone.now() + timedelta(minutes=hold_minutes_effective),
                price_snapshot=price_snapshot,
                policy_snapshot=policy_snapshot,
            )
            for line_no, (line, room_type, breakdown) in enumerate(quoted, start=1):
                ReservationLine.objects.create(
                    reservation=reservation,
                    line_no=line_no,
                    room_type=room_type,
                    arrival_date=line.stay_period.arrival,
                    departure_date=line.stay_period.departure,
                    quantity=line.quantity,
                    price_snapshot=breakdown.to_dict(),
                )

            for line_no, (line, room_type, _) in enumerate(quoted, start=1):
                InventoryService.hold(
                    tenant_id=tenant.id,
                    property_id=property.id,
                    room_type_id=room_type.id,
                    date_range=line.stay_period.as_date_range(),
                    quantity=line.quantity,
                    idempotency_key=f"{idempotency_key}:line:{line_no}",
                )

            WorkflowRunner(reservation, field="status").run("hold", reason="capacity held at quote")
            return {"reservation_id": reservation.id}

        response = IdempotencyService(tenant_id=tenant.id, scope="reservation.reserve").run(
            idempotency_key, request_payload, execute=_execute
        )
        return Reservation.objects.get(pk=response["reservation_id"])

    # ------------------------------------------------------------------
    # expire() — DB-authoritative TTL sweep (no Redis; status/lock based)
    # ------------------------------------------------------------------

    @classmethod
    def expire(cls, reservation_id: int) -> Reservation:
        """Release every line's hold and transition to Expired.

        Status/locking based, not idempotency-keyed (roadmap M8 ruling): a
        reservation already outside {Held, Awaiting_Payment} is a safe
        no-op, so a repeated sweep pass — or two sweep workers racing on the
        same overdue row — can never double-release or error.
        """
        with transaction.atomic():
            reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
            if reservation.status not in _UNSETTLED_STATUSES:
                return reservation
            for line in reservation.lines.all():
                InventoryService.release_hold(
                    tenant_id=reservation.tenant_id,
                    property_id=reservation.property_id,
                    room_type_id=line.room_type_id,
                    date_range=StayPeriod(line.arrival_date, line.departure_date).as_date_range(),
                    quantity=line.quantity,
                )
            return WorkflowRunner(reservation, field="status").run(
                "expire", reason="hold TTL elapsed"
            )

    @classmethod
    def _reject_if_hold_expired(cls, reservation: Reservation) -> None:
        """R0.3: the sweep (``expire()``, via Celery beat) is the periodic
        RECONCILER — it is not, and must not be, the only enforcement.
        Without this check, a Held/Awaiting_Payment reservation whose
        ``hold_expiry_at`` has already passed could still be converted into
        a real Booking in the window before the next sweep tick runs (or if
        no beat schedule is deployed at all). This is the authoritative,
        request-time guard: called under the row lock, before any
        transition, in both ``request_payment()`` and ``convert()``.

        Deliberately read-only (raises, never mutates): a mutation here
        would run inside the CALLER's own ``transaction.atomic()`` block
        (``convert()``/``request_payment()``), and raising immediately
        afterward to reject the action would roll back that same
        transaction — undoing the very expiry write this method just made.
        Actually flipping the row to Expired stays ``expire()``'s job
        (the sweep, or a direct call) — its own separate transaction.
        Until that runs, this guard alone is sufficient to make the
        invariant hold: every request-time attempt to act on an expired
        hold is rejected, unconditionally, regardless of whether the row's
        status has been reconciled to Expired yet."""
        if (
            reservation.status in _UNSETTLED_STATUSES
            and reservation.hold_expiry_at is not None
            and reservation.hold_expiry_at < timezone.now()
        ):
            raise TransitionNotAllowed(
                f"Reservation {reservation.id} hold expired at "
                f"{reservation.hold_expiry_at.isoformat()}; it can no longer be acted on."
            )

    # ------------------------------------------------------------------
    # cancel() — hold abandonment (no policy, no penalty — M8 ruling)
    # ------------------------------------------------------------------

    @classmethod
    def cancel(cls, *, tenant_id: int, reservation_id: int, idempotency_key: str) -> Reservation:
        """Release any held capacity and transition to Cancelled.

        Hold abandonment only — does NOT consult ``PolicyService`` (no
        payment has happened yet, so there is nothing to penalize).
        Idempotency-keyed like ``reserve()``; also domain-idempotent on top
        of that (a reservation already outside {Draft, Held,
        Awaiting_Payment} is left untouched regardless of key reuse).
        """
        request_payload = {"op": "cancel", "reservation_id": reservation_id}

        def _execute() -> dict:
            reservation = Reservation.objects.select_for_update().get(
                pk=reservation_id, tenant_id=tenant_id
            )
            if reservation.status in _UNSETTLED_STATUSES:
                for line in reservation.lines.all():
                    InventoryService.release_hold(
                        tenant_id=reservation.tenant_id,
                        property_id=reservation.property_id,
                        room_type_id=line.room_type_id,
                        date_range=StayPeriod(
                            line.arrival_date, line.departure_date
                        ).as_date_range(),
                        quantity=line.quantity,
                    )
                WorkflowRunner(reservation, field="status").run(
                    "cancel", reason="guest/staff abandoned the hold"
                )
            elif reservation.status == ReservationStatus.DRAFT:
                WorkflowRunner(reservation, field="status").run(
                    "cancel", reason="abandoned before hold"
                )
            return {"reservation_id": reservation.id}

        response = IdempotencyService(tenant_id=tenant_id, scope="reservation.cancel").run(
            idempotency_key, request_payload, execute=_execute
        )
        return Reservation.objects.get(pk=response["reservation_id"])

    # ------------------------------------------------------------------
    # convert() — reservation-side half of the (future) Booking handoff
    # ------------------------------------------------------------------

    @classmethod
    def convert(cls, reservation_id: int, *, tenant_id: int) -> Reservation:
        """Move every line's held capacity to sold and transition to
        Converted. Requires Awaiting_Payment (DDS S9 invariant #3: a
        reservation converts exactly once).

        ``tenant_id`` is required and filters the lookup itself (R0.1): the
        caller's tenant must own the reservation, enforced here rather than
        only at the API view, so no other entry point into this service can
        convert (and thereby consume inventory for, and create a Booking
        from) a reservation belonging to a different tenant. A wrong-tenant
        ``reservation_id`` raises the same ``Reservation.DoesNotExist`` as a
        genuinely nonexistent one — the caller cannot distinguish "not
        yours" from "doesn't exist".

        Deliberately does NOT create a Booking and does NOT set any
        ``converted_booking_id`` (that field does not exist yet — M9 will
        add it once the ``bookings`` app exists). M9's
        ``BookingService.confirm()`` calls this primitive inside its own
        larger atomic transaction.
        """
        with transaction.atomic():
            reservation = Reservation.objects.select_for_update().get(
                pk=reservation_id, tenant_id=tenant_id
            )
            cls._reject_if_hold_expired(reservation)
            if reservation.status != ReservationStatus.AWAITING_PAYMENT:
                raise TransitionNotAllowed(
                    f"Reservation {reservation_id} cannot convert from status "
                    f"{reservation.status!r}; requires 'awaiting_payment'."
                )
            for line in reservation.lines.all():
                InventoryService.convert_hold_to_sold(
                    tenant_id=reservation.tenant_id,
                    property_id=reservation.property_id,
                    room_type_id=line.room_type_id,
                    date_range=StayPeriod(line.arrival_date, line.departure_date).as_date_range(),
                    quantity=line.quantity,
                    idempotency_key=f"reservation:{reservation.id}:convert:line:{line.line_no}",
                )
            return WorkflowRunner(reservation, field="status").run(
                "convert", reason="payment succeeded"
            )

    # ------------------------------------------------------------------
    # request_payment() — completes the declared state machine (S9.3);
    # a later Payments milestone drives this from real guest action.
    # ------------------------------------------------------------------

    @classmethod
    def request_payment(cls, reservation_id: int, *, tenant_id: int) -> Reservation:
        """``tenant_id`` is required and filters the lookup (R0.1) — the API
        view already 404s a wrong-tenant id before calling this, but the
        guard belongs here too so no other caller can bypass it."""
        with transaction.atomic():
            reservation = Reservation.objects.select_for_update().get(
                pk=reservation_id, tenant_id=tenant_id
            )
            cls._reject_if_hold_expired(reservation)
            return WorkflowRunner(reservation, field="status").run(
                "request_payment", reason="guest reached the payment surface"
            )


class ReservationQuery:
    """Read-only selectors over ``reservation`` (mirrors ``RoomQuery``/``GuestQuery``)."""

    @staticmethod
    def overdue_holds(*, now=None):
        """The sweep's query — the partial-index hot path (DDS S9)."""
        cutoff = now or timezone.now()
        return Reservation.objects.filter(
            status__in=list(_UNSETTLED_STATUSES), hold_expiry_at__lt=cutoff
        )

    @staticmethod
    def by_reservation_ref(tenant, reservation_ref: str) -> Reservation | None:
        return Reservation.objects.filter(tenant=tenant, reservation_ref=reservation_ref).first()

    @staticmethod
    def by_guest(guest_profile):
        return Reservation.objects.filter(guest_profile=guest_profile).order_by("-created_at")

    @staticmethod
    def active_for_property(property):
        return Reservation.objects.filter(
            property=property, status__in=list(_UNSETTLED_STATUSES)
        ).order_by("hold_expiry_at")
