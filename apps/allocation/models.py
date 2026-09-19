"""AllocationRecord model (M11, DDS S12, DMS S12, DR-11).

``AllocationRecord`` is the durable "why this room?" decision — the
replayable artifact DMS S12 exists for, not just a side effect on ``Room``.
One row per ``BookingLine``, ever (``UniqueConstraint`` below): DDS S12's
``override`` column records that a human picked a different room than the
algorithm's top-scored candidate AT THE SAME decision point, not a later
re-allocation — there is no "move the guest" feature yet, so the row is
never updated after creation.

M11 semantic clarification (portfolio scope): allocation IS the physical
check-in boundary in this system —

    BookingLine.confirmed -> physical Room allocated -> BookingLine.checked_in

There is no separate "room assigned" vs. "guest checked in" distinction
here; a future milestone would have to deliberately introduce one (e.g. a
room pre-assignment step ahead of actual arrival) rather than assume it
already exists from this model shape.
"""

from django.db import models

from apps.shared.models.mixins import TimeStampedMixin


class AllocationRecord(TimeStampedMixin):
    """The recorded assignment decision for one ``BookingLine`` (DDS S12)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="allocation_records"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.RESTRICT, related_name="allocation_records"
    )
    booking_line = models.ForeignKey(
        "bookings.BookingLine", on_delete=models.RESTRICT, related_name="allocation_records"
    )
    room = models.ForeignKey(
        "rooms.Room", on_delete=models.RESTRICT, related_name="allocation_records"
    )
    chosen_by = models.ForeignKey(
        "accounts.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="allocation_decisions",
    )
    override = models.BooleanField(default=False)
    override_reason = models.TextField(blank=True, default="")
    # AllocationCriteria.to_dict() — the immutable input set (room_type_id,
    # guest_profile_id, candidate ids considered).
    criteria = models.JSONField(default=dict, blank=True)
    # {room_id: score, ...} for every candidate considered — replayability
    # (FR-ALL-02): "why this room, and not that one?" is always answerable.
    scores = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True, default="")

    objects = models.Manager()

    class Meta:
        app_label = "allocation"
        db_table = "allocation_record"
        constraints = [
            models.UniqueConstraint(
                fields=["booking_line"], name="allocation_record_uq_booking_line"
            ),
        ]
        indexes = [
            models.Index(fields=["room", "-created_at"], name="alloc_record_ix_room_created"),
        ]

    def __str__(self) -> str:
        return f"line={self.booking_line_id} -> room={self.room_id}"
