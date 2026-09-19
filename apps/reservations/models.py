"""Reservation models (M8, SDD S9.3/S10.1/S11.4, DDS S9).

``Reservation`` is the pre-payment commercial intent: quote -> hold -> convert
/ expire / cancel. It is the transaction boundary for the capacity hold and
its TTL (DR-05, DR-08) — never a source of price or policy truth (it asks
Pricing/Policy and pins their answers; see ``apps/reservations/services.py``).

Not partitioned (DDS D5 only partitions ``availability_slot``; reservation
volume is orders of magnitude smaller) and not RLS-enabled yet — M7 deferred
RLS on ``availability_slot`` with the same reasoning, and M8 follows that
precedent rather than introducing a new one.

Pessimistically locked on every lifecycle transition (``select_for_update()``
in ``ReservationService``, matching DDS S9's explicit ``LOCK pessimistic``
note) — deliberately NOT ``EntityMixin``/``VersionedMixin``: this aggregate's
concurrency story is row locks, not optimistic retry (mirrors the M7
``AvailabilitySlot`` ruling).
"""

from django.db import models
from django_fsm import FSMField

from apps.availability.models import Channel
from apps.shared.models.mixins import TimeStampedMixin, WorkflowStateGuardMixin
from apps.shared.models.recipes import partial_index, status_constraint
from apps.shared.workflows.runner import workflow_transition


class ReservationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    HELD = "held", "Held"
    AWAITING_PAYMENT = "awaiting_payment", "Awaiting Payment"
    CONVERTED = "converted", "Converted"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"


_UNSETTLED_STATUSES = (ReservationStatus.HELD, ReservationStatus.AWAITING_PAYMENT)


class Reservation(WorkflowStateGuardMixin, TimeStampedMixin):
    """The pre-payment commercial intent (DDS S9 ``reservation``).

    ``status`` is WorkflowRunner-governed (R0.6) — ``WorkflowStateGuardMixin``
    rejects any save() that changes it outside a declared transition.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="reservations"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.RESTRICT, related_name="reservations"
    )
    guest_profile = models.ForeignKey(
        "guests.GuestProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reservations",
    )
    reservation_ref = models.CharField(max_length=32)
    status = FSMField(
        max_length=20, choices=ReservationStatus.choices, default=ReservationStatus.DRAFT
    )
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.DIRECT)
    hold_expiry_at = models.DateTimeField(null=True, blank=True)

    # PriceBreakdown.to_dict() aggregate roll-up — captured at reserve() time,
    # never recomputed (DMS S9 invariant #5). Never read by this app for math.
    price_snapshot = models.JSONField(default=dict, blank=True)
    # {"deposit": {"policy_id": int, "version": int, "answer": {...}}} — pinned
    # policy refs + the exact answer Policy gave, never the policy's raw
    # `rules` JSON re-interpreted here (DR-10).
    policy_snapshot = models.JSONField(default=dict, blank=True)

    objects = models.Manager()

    class Meta:
        app_label = "reservations"
        db_table = "reservation"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "reservation_ref"], name="reservation_uq_tenant_ref"
            ),
            status_constraint("status", ReservationStatus, "reservation_valid_status"),
            models.CheckConstraint(
                condition=(
                    models.Q(hold_expiry_at__isnull=True)
                    | models.Q(hold_expiry_at__gt=models.F("created_at"))
                ),
                name="reservation_hold_expiry_after_created",
            ),
        ]
        indexes = [
            partial_index(
                ["property", "status", "hold_expiry_at"],
                models.Q(status__in=list(_UNSETTLED_STATUSES)),
                "reservation_ix_sweep_hot_path",
            ),
            models.Index(fields=["guest_profile"], name="reservation_ix_guest"),
            models.Index(fields=["created_at"], name="reservation_ix_created"),
        ]

    def __str__(self) -> str:
        return f"{self.reservation_ref} ({self.status})"

    # ------------------------------------------------------------------
    # State machine (SDD S9.3) — declared here, orchestrated exclusively by
    # ReservationService through WorkflowRunner (M3 Room pattern).
    # ------------------------------------------------------------------

    @workflow_transition(
        field="status",
        source=ReservationStatus.DRAFT,
        target=ReservationStatus.HELD,
        event="reservation.created",
    )
    def hold(self):
        """Capacity held for every line — the quote becomes a live hold."""

    @workflow_transition(
        field="status",
        source=ReservationStatus.HELD,
        target=ReservationStatus.AWAITING_PAYMENT,
        event=None,  # not in the frozen event catalog (SDD S12) — no consumer yet
    )
    def request_payment(self):
        """Guest reached the payment surface (SDD S9.3). No M8 caller emits
        this from user action yet — Payments (a later milestone) will drive
        it; it exists now purely to complete the declared state machine so
        ``convert()``'s required source state is reachable at all."""

    @workflow_transition(
        field="status",
        source=[ReservationStatus.HELD, ReservationStatus.AWAITING_PAYMENT],
        target=ReservationStatus.EXPIRED,
        event="reservation.expired",
    )
    def expire(self):
        """TTL elapsed — the sweep's transition."""

    @workflow_transition(
        field="status",
        source=[
            ReservationStatus.DRAFT,
            ReservationStatus.HELD,
            ReservationStatus.AWAITING_PAYMENT,
        ],
        target=ReservationStatus.CANCELLED,
        event=None,  # explicitly NOT added to the frozen catalog (M8 ruling)
    )
    def cancel(self):
        """Guest/staff abandons the hold. No penalty here — hold abandonment
        only; cancellation penalties are a Booking/Payment-era concern."""

    @workflow_transition(
        field="status",
        source=ReservationStatus.AWAITING_PAYMENT,
        target=ReservationStatus.CONVERTED,
        event="reservation.converted",
    )
    def convert(self):
        """Payment succeeded — the reservation-side half of the (future)
        Booking handoff. See ``ReservationService.convert()``."""


class ReservationLine(TimeStampedMixin):
    """Per-room-type-line: stay period, quantity, price snapshot (DDS S9
    ``reservation_line``). Never references a physical ``Room`` (DR-05)."""

    reservation = models.ForeignKey(Reservation, on_delete=models.RESTRICT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    room_type = models.ForeignKey(
        "rooms.RoomType", on_delete=models.RESTRICT, related_name="reservation_lines"
    )
    arrival_date = models.DateField()
    departure_date = models.DateField()
    quantity = models.PositiveIntegerField()
    # Per-line PriceBreakdown.to_dict() — the same snapshot rule as the
    # aggregate (S7 above); computed once by PricingService, never recomputed.
    price_snapshot = models.JSONField(default=dict, blank=True)

    objects = models.Manager()

    class Meta:
        app_label = "reservations"
        db_table = "reservation_line"
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "line_no"], name="reservation_line_uq_reservation_lineno"
            ),
            models.CheckConstraint(
                condition=models.Q(departure_date__gt=models.F("arrival_date")),
                name="reservation_line_departure_after_arrival",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="reservation_line_quantity_positive"
            ),
        ]
        indexes = [
            models.Index(fields=["reservation"], name="reservation_line_ix_resv"),
        ]

    def __str__(self) -> str:
        return f"{self.reservation_id}:{self.line_no} {self.room_type_id}"
