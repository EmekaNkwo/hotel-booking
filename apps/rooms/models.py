"""Room models (M3).

Room operational state machine + audit trail. No partitioning in M3 (deferred to M7).
"""

from django.db import models
from django_fsm import FSMField

from apps.shared.models.mixins import EntityMixin
from apps.shared.tenancy import TenantScopedManager

# State transition enforcement - import from shared kernel
from apps.shared.workflows.context import is_workflow_active
from apps.shared.workflows.runner import workflow_transition


class RoomType(EntityMixin):
    """Sellable room type (e.g., Standard King)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="room_types",
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    max_occupancy = models.PositiveSmallIntegerField()
    attributes = models.JSONField(default=dict, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="unique_room_type_code_per_tenant",
            ),
            models.CheckConstraint(
                check=models.Q(status__in=["active", "retired"]),
                name="room_type_valid_status",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self):
        return f"{self.code}: {self.name}"


class Room(EntityMixin):
    """Physical room. Owns the operational state machine."""

    class OperationalState(models.TextChoices):
        VACANT_CLEAN = "vacant_clean", "Vacant Clean"
        VACANT_DIRTY = "vacant_dirty", "Vacant Dirty"
        OCCUPIED_CLEAN = "occupied_clean", "Occupied Clean"
        OCCUPIED_DIRTY = "occupied_dirty", "Occupied Dirty"
        OUT_OF_SERVICE = "out_of_service", "Out of Service"
        OUT_OF_ORDER = "out_of_order", "Out of Order"
        CLEANING = "cleaning", "Cleaning"  # Ephemeral
        INSPECTED = "inspected", "Inspected"  # Ephemeral

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="rooms",
    )
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.RESTRICT,
        related_name="rooms",
    )
    room_type = models.ForeignKey(
        RoomType,
        on_delete=models.RESTRICT,
        related_name="rooms",
    )
    code = models.CharField(max_length=32)  # e.g., "101", "202A"
    building = models.ForeignKey(
        "properties.Building",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rooms",
    )
    floor = models.ForeignKey(
        "properties.Floor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rooms",
    )
    operational_state = FSMField(
        max_length=32,
        choices=OperationalState.choices,
        default=OperationalState.VACANT_CLEAN,
    )
    current_booking_line_id = models.BigIntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "code"],
                name="unique_room_code_per_property",
            ),
            models.CheckConstraint(
                check=models.Q(
                    operational_state__in=[
                        "vacant_clean",
                        "vacant_dirty",
                        "occupied_clean",
                        "occupied_dirty",
                        "out_of_service",
                        "out_of_order",
                        "cleaning",
                        "inspected",
                    ]
                ),
                name="room_valid_operational_state",
            ),
        ]
        indexes = [
            models.Index(fields=["property"]),
            models.Index(fields=["room_type"]),
            # Allocation hot path: find Vacant Clean rooms of a given type
            models.Index(
                fields=["room_type", "id"],
                name="room_vacant_clean_idx",
                condition=models.Q(operational_state="vacant_clean"),
            ),
        ]

    def __str__(self):
        return f"{self.property.code}:{self.code}"

    # State machine transitions using django-fsm
    @workflow_transition(
        field="operational_state",
        source=OperationalState.VACANT_CLEAN,
        target=OperationalState.OCCUPIED_CLEAN,
        event="room.state_changed",
    )
    def allocate(self):
        """Allocate a vacant clean room to a guest."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.OCCUPIED_CLEAN,
        target=OperationalState.OCCUPIED_DIRTY,
        event="room.state_changed",
    )
    def service(self):
        """Mark room as needing service while occupied."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.OCCUPIED_DIRTY,
        target=OperationalState.OCCUPIED_CLEAN,
        event="room.state_changed",
    )
    def service_complete(self):
        """Complete service on occupied room."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.OCCUPIED_CLEAN,
        target=OperationalState.VACANT_DIRTY,
        event="room.state_changed",
    )
    def checkout(self):
        """Guest checks out, room becomes vacant dirty."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.VACANT_DIRTY,
        target=OperationalState.CLEANING,
        event="room.state_changed",
    )
    def clean(self):
        """Start cleaning process."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.CLEANING,
        target=OperationalState.INSPECTED,
        event="room.state_changed",
    )
    def complete_cleaning(self):
        """Complete cleaning, ready for inspection."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.INSPECTED,
        target=OperationalState.VACANT_CLEAN,
        event="room.state_changed",
    )
    def approve(self):
        """Approve inspection, room is ready for allocation."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.INSPECTED,
        target=OperationalState.CLEANING,
        event="room.state_changed",
    )
    def reject(self):
        """Reject inspection, needs more cleaning."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.VACANT_CLEAN,
        target=OperationalState.OUT_OF_SERVICE,
        event="room.state_changed",
    )
    def defect(self):
        """Mark room as out of service due to defect."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.OCCUPIED_CLEAN,
        target=OperationalState.OUT_OF_ORDER,
        event="room.state_changed",
    )
    def maintenance(self):
        """Mark room as out of order for maintenance."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.OUT_OF_SERVICE,
        target=OperationalState.CLEANING,
        event="room.state_changed",
    )
    def restore(self):
        """Restore room from out of service (must go through cleaning)."""
        pass

    @workflow_transition(
        field="operational_state",
        source=OperationalState.OUT_OF_ORDER,
        target=OperationalState.VACANT_CLEAN,
        event="room.state_changed",
    )
    def restore_direct(self):
        """Restore room from out of order directly (no cleaning needed)."""
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Track original state for enforcement
        self._original_operational_state = self.operational_state

    def save(self, *args, **kwargs):
        """Enforce that state changes must go through RoomStateMachine.

        If the operational_state has changed and we're not in a workflow context,
        reject the save to prevent bypassing audit/outbox/permissions.
        """
        # Check if state changed
        state_changed = (
            self.pk is not None and  # Existing instance
            hasattr(self, '_original_operational_state') and
            self._original_operational_state != self.operational_state
        )

        # If state changed outside workflow context, reject
        if state_changed and not is_workflow_active():
            raise ValueError(
                f"Room state changes must go through RoomStateMachine.apply(). "
                f"Attempted to change state from {self._original_operational_state} "
                f"to {self.operational_state} without proper workflow context."
            )

        # Normal save
        super().save(*args, **kwargs)

        # Update tracked state after successful save
        self._original_operational_state = self.operational_state


class RoomStateEvent(EntityMixin):
    """Append-only room state audit trail. NOT partitioned in M3 (deferred to M7)."""

    class Transition(models.TextChoices):
        ALLOCATE = "allocate", "Allocate"
        CHECKOUT = "checkout", "Checkout"
        CLEAN = "clean", "Clean"
        COMPLETE_CLEANING = "complete_cleaning", "Complete Cleaning"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        DEFECT = "defect", "Defect"
        MAINTENANCE = "maintenance", "Maintenance"
        RESTORE = "restore", "Restore"
        RESTORE_DIRECT = "restore_direct", "Restore Direct"
        SERVICE = "service", "Service"
        SERVICE_COMPLETE = "service_complete", "Service Complete"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="room_state_events",
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.RESTRICT,
        related_name="state_events",
    )
    from_state = models.CharField(max_length=32)
    to_state = models.CharField(max_length=32)
    transition = models.CharField(
        max_length=32,
        choices=Transition.choices,
    )
    actor_id = models.BigIntegerField()
    actor_type = models.CharField(max_length=64)
    reason = models.TextField(blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(
                    transition__in=[
                        "allocate",
                        "checkout",
                        "clean",
                        "complete_cleaning",
                        "approve",
                        "reject",
                        "defect",
                        "maintenance",
                        "restore",
                        "restore_direct",
                        "service",
                        "service_complete",
                    ]
                ),
                name="room_state_event_valid_transition",
            ),
        ]
        indexes = [
            models.Index(fields=["room"]),
            models.Index(fields=["created_at"]),  # Chronological ordering
        ]

    def __str__(self):
        return f"{self.room.property.code}:{self.room.code} {self.from_state}→{self.to_state}"


class RoomConnection(EntityMixin):
    """Symmetric connecting-room links (e.g., adjoining rooms)."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="room_connections",
    )
    room_a = models.ForeignKey(
        Room,
        on_delete=models.RESTRICT,
        related_name="connections_as_a",
    )
    room_b = models.ForeignKey(
        Room,
        on_delete=models.RESTRICT,
        related_name="connections_as_b",
    )
    connection_type = models.CharField(max_length=64)  # e.g., "adjoining", "connecting"

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["room_a", "room_b"],
                name="unique_room_connection_pair",
            ),
            models.CheckConstraint(
                check=~models.Q(room_a=models.F("room_b")),
                name="room_connection_no_self_loop",
            ),
        ]
        indexes = [
            models.Index(fields=["room_a"]),
            models.Index(fields=["room_b"]),
        ]

    def __str__(self):
        return f"{self.room_a} ↔ {self.room_b} ({self.connection_type})"


class RoomQuery:
    """Selector for room allocation and reporting."""

    @staticmethod
    def vacant_clean_candidates(room_type_id: int):
        """Allocation hot path: Vacant Clean rooms of a given type."""
        return Room.objects.filter(
            room_type_id=room_type_id,
            operational_state=Room.OperationalState.VACANT_CLEAN,
            deleted_at__isnull=True,
        ).select_related("property", "room_type")

    @staticmethod
    def by_property(property_id: int):
        """All rooms for a property."""
        return Room.objects.filter(
            property_id=property_id,
            deleted_at__isnull=True,
        ).select_related("property", "room_type", "building", "floor")

    @staticmethod
    def with_attributes(attributes: dict):
        """Rooms whose room_type has the given attributes."""
        return Room.objects.filter(
            room_type__attributes__contains=attributes,
            deleted_at__isnull=True,
        ).select_related("property", "room_type")