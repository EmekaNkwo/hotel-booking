"""Availability & Inventory models (M7, DDS S6+7, DR-05).

One merged table set. ``AvailabilitySlot`` is the anti-oversell row —
``AvailabilityService`` (reads, horizon init) and ``InventoryService``
(consume/release/convert) share it (D2: "one aggregate, one table set").
Both services live in THIS single app rather than being split into
``availability``/``inventory`` Django apps: D2 explicitly permits either
shape ("two apps permitted only if `inventory` calls `availability` services
exclusively — CI-enforced"); one app removes the need to invent and enforce
that import boundary for a table the two services share 1:1, with zero
production benefit at this milestone.

``AvailabilitySlot`` is the project's FIRST genuinely partitioned table
(E7) — PostgreSQL creates it ``PARTITION BY RANGE (business_date)`` with a
composite primary key ``(business_date, id)`` (D5: the partition key must be
part of the PK; ``id`` stays the app-level surrogate reference). See
``apps/availability/migrations/0001_initial.py`` and
``apps/availability/partitioning.py`` for the real DDL — SQLite (unit tier)
gets the ordinary, non-partitioned Django table instead; only PostgreSQL
requires and gets the partitioned structure.

``id`` is deliberately NOT the model's primary key field (the composite
``pk`` is — mirrors the ``PolicyEvaluationLog`` pattern from M4, DDS S21).
Because of that, Django's normal auto-pk-assignment path never fires for it,
so every insert must supply a value explicitly — see
``apps/availability/partitioning.py::reserve_slot_ids`` for the portable
(Postgres sequence / SQLite MAX+1) allocator every write path uses.
"""

from django.db import models
from django.db.models.fields.composite import CompositePrimaryKey

from apps.shared.models.mixins import TimeStampedMixin
from apps.shared.models.recipes import partial_index, status_constraint


class Channel(models.TextChoices):
    """Per-channel capacity rule scope (DDS S7). v1 ships direct-only (DR-03)."""

    DIRECT = "direct", "Direct"


class AvailabilitySlot(TimeStampedMixin):
    """The anti-oversell row: one per (tenant, property, room_type, channel, date).

    ``total_units`` is the sellable room-type capacity for that night — a
    commercial decision Availability owns explicitly (never derived from
    physical ``Room`` rows; SDD S11.2, DR-05: sales never touch rooms).
    ``remaining`` is a STORED generated column so it can never drift from its
    inputs (DR-05) and stays indexable/filterable.

    Every consume/release is a ``SELECT ... FOR UPDATE`` over the affected
    window (pessimistic — DDS S6 LOCK note, R1) followed by a plain
    conditional UPDATE; see ``AvailabilitySlotRepository``. Rows are never
    updated outside that repository.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="availability_slots",
    )
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.RESTRICT,
        related_name="availability_slots",
    )
    room_type = models.ForeignKey(
        "rooms.RoomType",
        on_delete=models.RESTRICT,
        related_name="availability_slots",
    )
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.DIRECT)
    business_date = models.DateField()

    # Surrogate reference (D5) — NOT the primary key; see module docstring.
    id = models.BigIntegerField(editable=False)

    total_units = models.PositiveIntegerField()
    sold = models.PositiveIntegerField(default=0)
    reserved = models.PositiveIntegerField(default=0)
    blocked = models.PositiveIntegerField(default=0)
    out_of_service = models.PositiveIntegerField(default=0)
    remaining = models.GeneratedField(
        expression=(
            models.F("total_units")
            - models.F("sold")
            - models.F("reserved")
            - models.F("blocked")
            - models.F("out_of_service")
        ),
        output_field=models.IntegerField(),
        db_persist=True,
    )

    pk = CompositePrimaryKey("business_date", "id")

    objects = models.Manager()

    class Meta:
        app_label = "availability"
        db_table = "availability_slot"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "property", "room_type", "channel", "business_date"],
                name="availability_slot_uq_tenant_property_roomtype_channel_date",
            ),
            status_constraint("channel", Channel, "availability_slot_valid_channel"),
            models.CheckConstraint(
                condition=(
                    models.Q(total_units__gte=0)
                    & models.Q(sold__gte=0)
                    & models.Q(reserved__gte=0)
                    & models.Q(blocked__gte=0)
                    & models.Q(out_of_service__gte=0)
                ),
                name="availability_slot_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total_units__gte=(
                        models.F("sold")
                        + models.F("reserved")
                        + models.F("blocked")
                        + models.F("out_of_service")
                    )
                ),
                name="availability_slot_within_total",
            ),
        ]
        indexes = [
            partial_index(
                ["tenant", "property", "room_type", "business_date"],
                models.Q(remaining__gt=0),
                "availability_slot_ix_sellable",
            ),
            models.Index(
                fields=["room_type", "business_date"], name="availability_slot_ix_rt_date"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.property_id}:{self.room_type_id}:{self.channel}:{self.business_date}"


class InventoryBlockStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    CONFIRMED = "confirmed", "Confirmed"
    RELEASED = "released", "Released"
    PICKED_UP = "picked_up", "Picked up"


class InventoryBlock(TimeStampedMixin):
    """A group/block hold (DDS S7). Scaffolding only in M7 — the confirm/
    pick-up orchestration ships with group bookings in v2 (FR-BOOK-05)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="inventory_blocks"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.RESTRICT, related_name="inventory_blocks"
    )
    room_type = models.ForeignKey(
        "rooms.RoomType", on_delete=models.RESTRICT, related_name="inventory_blocks"
    )
    name = models.CharField(max_length=128)
    start_date = models.DateField()
    end_date = models.DateField()
    quantity = models.PositiveIntegerField()
    status = models.CharField(
        max_length=16, choices=InventoryBlockStatus.choices, default=InventoryBlockStatus.DRAFT
    )

    objects = models.Manager()

    class Meta:
        app_label = "availability"
        db_table = "inventory_block"
        constraints = [
            models.UniqueConstraint(
                fields=["property", "name"], name="inventory_block_uq_property_name"
            ),
            status_constraint("status", InventoryBlockStatus, "inventory_block_valid_status"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="inventory_block_quantity_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="inventory_block_end_on_or_after_start",
            ),
            # The GiST EXCLUDE for real non-overlap-per-room-type is
            # Postgres-only, applied out-of-band in
            # 0002_exclude_inventory_overlap.py — see that migration's
            # docstring (mirrors apps/pricing/migrations/0002).
        ]
        indexes = [
            models.Index(fields=["property", "room_type", "start_date", "end_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.status})"


class InventoryBlockNight(TimeStampedMixin):
    """Materialized per-night block claim (DDS S7) — reconciliation only."""

    block = models.ForeignKey(InventoryBlock, on_delete=models.CASCADE, related_name="nights")
    room_type = models.ForeignKey(
        "rooms.RoomType", on_delete=models.RESTRICT, related_name="inventory_block_nights"
    )
    business_date = models.DateField()

    objects = models.Manager()

    class Meta:
        app_label = "availability"
        db_table = "inventory_block_night"
        constraints = [
            models.UniqueConstraint(
                fields=["block", "business_date"], name="inventory_block_night_uq_block_date"
            ),
        ]
        indexes = [
            models.Index(fields=["business_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.block_id}:{self.business_date}"


class ChannelAllocationMode(models.TextChoices):
    FIXED = "fixed", "Fixed"
    PERCENTAGE = "percentage", "Percentage"
    POOL = "pool", "Pool"


class ChannelOversellPolicy(models.TextChoices):
    NONE = "none", "None"
    LIMITED = "limited", "Limited"


class ChannelAllocation(TimeStampedMixin):
    """Per-channel capacity rule (DDS S7). v1: direct-only (DR-03) — the seam
    v3's channel manager plugs into. Scaffolding only in M7."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="channel_allocations"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.RESTRICT, related_name="channel_allocations"
    )
    room_type = models.ForeignKey(
        "rooms.RoomType", on_delete=models.RESTRICT, related_name="channel_allocations"
    )
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.DIRECT)
    start_date = models.DateField()
    end_date = models.DateField()
    mode = models.CharField(max_length=16, choices=ChannelAllocationMode.choices)
    value = models.PositiveIntegerField()
    oversell_policy = models.CharField(
        max_length=16, choices=ChannelOversellPolicy.choices, default=ChannelOversellPolicy.NONE
    )
    active = models.BooleanField(default=True)

    objects = models.Manager()

    class Meta:
        app_label = "availability"
        db_table = "channel_allocation"
        constraints = [
            status_constraint("mode", ChannelAllocationMode, "channel_allocation_valid_mode"),
            status_constraint(
                "oversell_policy", ChannelOversellPolicy, "channel_allocation_valid_oversell_policy"
            ),
            models.CheckConstraint(
                condition=models.Q(value__gt=0), name="channel_allocation_value_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="channel_allocation_end_on_or_after_start",
            ),
            # GiST EXCLUDE for non-overlap-per-room-type: Postgres-only,
            # applied in 0002_exclude_inventory_overlap.py.
        ]
        indexes = [
            models.Index(fields=["property", "room_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.room_type_id}:{self.channel} {self.mode}={self.value}"
