"""Booking models (M9, SDD S9.3/S10.2, DDS S10).

``Booking`` is the confirmed commercial agreement — the aggregate root
DMS S10 describes as ``confirmed -> completed/cancelled``. It never
recomputes price, never re-interprets policy, never resolves guest identity,
and never touches ``AvailabilitySlot`` — it is created from an already
``Converted`` ``Reservation`` (M8) by ``BookingService.confirm()``, which
copies that reservation's pinned snapshots verbatim.

Status enum note (M9 ruling): the DB CHECK constraint carries the FULL DDS
enum (inquiry .. early_departure) for schema fidelity with the frozen doc,
even though M9 only ever wires ONE transition
(``pending_payment -> confirmed``). The pre-confirmation states are
Reservation's (M8) job; the post-confirmation operational states
(checked_in, in_house, ...) belong to later milestones (Allocation,
Housekeeping, Payments) that do not exist yet. Declaring them now avoids a
schema migration later just to widen a closed set.

Not partitioned (DDS D5 only names ``availability_slot``) and not
RLS-enabled — same deferral precedent as M7/M8. Pessimistically locked
(DDS A.6: ``booking``/``booking_line`` locked on modify/cancel/check-in) —
deliberately NOT ``EntityMixin``/``VersionedMixin``, matching ``Reservation``.
"""

from django.db import models
from django_fsm import FSMField

from apps.shared.models.mixins import TimeStampedMixin, WorkflowStateGuardMixin
from apps.shared.models.recipes import status_constraint
from apps.shared.workflows.runner import workflow_transition


class BookingStatus(models.TextChoices):
    """The full DDS S10 enum. M9 only ever produces/transitions PENDING_PAYMENT
    -> CONFIRMED; every other value is reserved for a later milestone."""

    INQUIRY = "inquiry", "Inquiry"
    QUOTE = "quote", "Quote"
    PENDING_PAYMENT = "pending_payment", "Pending Payment"
    CONFIRMED = "confirmed", "Confirmed"
    CHECKED_IN = "checked_in", "Checked In"
    IN_HOUSE = "in_house", "In House"
    CHECKED_OUT = "checked_out", "Checked Out"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    NO_SHOW = "no_show", "No Show"
    EARLY_DEPARTURE = "early_departure", "Early Departure"


class Booking(WorkflowStateGuardMixin, TimeStampedMixin):
    """The confirmed commercial agreement (DDS S10 ``booking``).

    ``aggregate_status`` is WorkflowRunner-governed (R0.6) —
    ``WorkflowStateGuardMixin`` rejects any save() that changes it outside a
    declared transition. (``BookingLine.status``, below, is deliberately
    NOT guarded — see its own docstring.)
    """

    workflow_guarded_field = "aggregate_status"

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.RESTRICT, related_name="bookings")
    property = models.ForeignKey(
        "properties.Property", on_delete=models.RESTRICT, related_name="bookings"
    )
    reservation = models.ForeignKey(
        "reservations.Reservation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )
    guest_profile = models.ForeignKey(
        "guests.GuestProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )
    booking_ref = models.CharField(max_length=32)
    aggregate_status = FSMField(
        max_length=20, choices=BookingStatus.choices, default=BookingStatus.PENDING_PAYMENT
    )
    currency = models.CharField(max_length=3)
    total_minor_units = models.BigIntegerField()
    arrival_date = models.DateField()
    departure_date = models.DateField()

    # Copied verbatim from the converting Reservation (M8) — never
    # recomputed, never re-queried from Pricing/Policy (DMS invariant #4).
    price_snapshot = models.JSONField(default=dict, blank=True)
    policy_snapshot = models.JSONField(default=dict, blank=True)
    # {"name": ..., "email": ..., "phone": ...} — captured from the
    # reservation's already-resolved guest at confirm time (DMS invariant #8:
    # a profile merge must never rewrite booking history).
    guest_snapshot = models.JSONField(default=dict, blank=True)

    objects = models.Manager()

    class Meta:
        app_label = "bookings"
        db_table = "booking"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "booking_ref"], name="booking_uq_tenant_ref"),
            models.UniqueConstraint(fields=["reservation"], name="booking_uq_reservation"),
            status_constraint("aggregate_status", BookingStatus, "booking_valid_status"),
            models.CheckConstraint(
                condition=models.Q(total_minor_units__gte=0), name="booking_total_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(currency__regex=r"^[A-Z]{3}$"), name="booking_currency_iso3"
            ),
            models.CheckConstraint(
                condition=models.Q(departure_date__gt=models.F("arrival_date")),
                name="booking_departure_after_arrival",
            ),
        ]
        indexes = [
            models.Index(
                fields=["property", "arrival_date", "aggregate_status"],
                name="booking_ix_prop_arr_status",
            ),
            models.Index(fields=["guest_profile"], name="booking_ix_guest"),
            models.Index(fields=["created_at"], name="booking_ix_created"),
        ]

    def __str__(self) -> str:
        return f"{self.booking_ref} ({self.aggregate_status})"

    # ------------------------------------------------------------------
    # State machine (M9 ruling): ONLY pending_payment -> confirmed wired.
    # ------------------------------------------------------------------

    @workflow_transition(
        field="aggregate_status",
        source=BookingStatus.PENDING_PAYMENT,
        target=BookingStatus.CONFIRMED,
        event="booking.confirmed",
    )
    def confirm(self):
        """Reservation converted, inventory sold, lines fanned out — commit."""


class BookingLine(TimeStampedMixin):
    """One physical-room-equivalent line (DDS S10 ``booking_line``).

    ``room`` is always NULL in M9 — Allocation (M11) assigns it at
    check-in. Created directly at ``status="confirmed"`` alongside the
    ``Booking`` root's own transition (M9 ruling: no per-line FSM/audit/
    event in this milestone). ``status`` is a plain field, by design —
    Allocation (M11) and Housekeeping (M12) both mutate it directly
    (``room = room; status = CHECKED_IN`` / ``status = CHECKED_OUT``), not
    through a declared transition, so it deliberately does NOT get
    ``WorkflowStateGuardMixin`` (R0.6): there is no per-line FSM for that
    guard to enforce against. Correctness here rests on each caller's own
    row lock + precondition check, not a model-level guard.
    """

    booking = models.ForeignKey(Booking, on_delete=models.RESTRICT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    room_type = models.ForeignKey(
        "rooms.RoomType", on_delete=models.RESTRICT, related_name="booking_lines"
    )
    room = models.ForeignKey(
        "rooms.Room",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="booking_lines",
    )
    arrival_date = models.DateField()
    departure_date = models.DateField()
    status = models.CharField(max_length=20, choices=BookingStatus.choices)
    # Copied verbatim from the source ReservationLine — every fanned-out
    # line for one ReservationLine(quantity=N) gets an identical copy (the
    # snapshot describes the room-type/date-range price, not a specific
    # physical unit).
    price_snapshot = models.JSONField(default=dict, blank=True)

    objects = models.Manager()

    class Meta:
        app_label = "bookings"
        db_table = "booking_line"
        constraints = [
            models.UniqueConstraint(
                fields=["booking", "line_no"], name="booking_line_uq_booking_lineno"
            ),
            status_constraint("status", BookingStatus, "booking_line_valid_status"),
            models.CheckConstraint(
                condition=models.Q(departure_date__gt=models.F("arrival_date")),
                name="booking_line_departure_after_arrival",
            ),
        ]
        indexes = [
            models.Index(fields=["booking"], name="booking_line_ix_booking"),
            models.Index(
                fields=["room"],
                name="booking_line_ix_room_active",
                condition=models.Q(room__isnull=False)
                & ~models.Q(status__in=[BookingStatus.CANCELLED, BookingStatus.COMPLETED]),
            ),
            models.Index(
                fields=["arrival_date", "status"],
                name="booking_line_ix_arrivals",
                condition=models.Q(status__in=[BookingStatus.CONFIRMED, BookingStatus.CHECKED_IN]),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.booking_id}:{self.line_no} {self.room_type_id}"
