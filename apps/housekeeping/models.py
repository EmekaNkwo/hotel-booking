"""Housekeeping models (M12, DDS S13, SDD S10.3).

``HousekeepingTask`` tracks the clean -> inspect loop for one room on one
business date; ``Inspection`` is the immutable pass/fail verdict. Both
compose the existing M3 ``Room`` FSM (via ``RoomStateMachine`` in
``services.py``) rather than owning any operational-state truth themselves
— Room remains the single authority for ``operational_state``.

Locking (DDS A.6, explicit ruling): ``HousekeepingTask`` is OPTIMISTIC
(``EntityMixin`` -> ``VersionedMixin``) — "assignment races are
low-frequency; room state is the pessimistic one." Room's own locking is
unchanged M3 (also ``VersionedMixin``, per the M11 finding). No
``select_for_update()`` appears anywhere in this app.

Scope (M12 ruling): no ``hk_standard``/``hk_plan`` (deferred), no
``priority``/``due_at`` (not in the authoritative ``housekeeping_task``
schema), no OOS routing (a failed inspection sends the room back to
``CLEANING`` via the existing ``reject`` transition, never to
``OUT_OF_SERVICE`` — that Room edge doesn't exist in the shipped M3 FSM and
this milestone does not add it).
"""

from django.db import models
from django_fsm import FSMField

from apps.shared.models.mixins import EntityMixin, TimeStampedMixin, WorkflowStateGuardMixin
from apps.shared.models.recipes import status_constraint
from apps.shared.tenancy import TenantScopedManager
from apps.shared.workflows.runner import workflow_transition


class TaskKind(models.TextChoices):
    """DDS S13 closed set. M12 only ever produces DEPARTURE tasks — the
    others are declared for schema fidelity, unreachable until a
    night-audit/manual-trigger milestone exists."""

    DEPARTURE = "departure", "Departure"
    DAILY = "daily", "Daily"
    DEFECT = "defect", "Defect"
    DEEP_CLEAN = "deep_clean", "Deep Clean"


class TaskStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    ASSIGNED = "assigned", "Assigned"
    IN_PROGRESS = "in_progress", "In Progress"
    QUALITY_CHECK = "quality_check", "Quality Check"
    VERIFIED = "verified", "Verified"
    DEFECT = "defect", "Defect"


class HousekeepingTask(WorkflowStateGuardMixin, EntityMixin):
    """One clean/inspect job for one room, one business date (DDS S13).

    ``status`` is WorkflowRunner-governed (R0.6) — ``WorkflowStateGuardMixin``
    rejects any save() that changes it outside a declared transition.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="housekeeping_tasks"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.RESTRICT, related_name="housekeeping_tasks"
    )
    room = models.ForeignKey(
        "rooms.Room", on_delete=models.RESTRICT, related_name="housekeeping_tasks"
    )
    booking_line = models.ForeignKey(
        "bookings.BookingLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="housekeeping_tasks",
    )
    business_date = models.DateField()
    task_kind = models.CharField(max_length=16, choices=TaskKind.choices)
    status = FSMField(max_length=16, choices=TaskStatus.choices, default=TaskStatus.PLANNED)
    assignee = models.ForeignKey(
        "accounts.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="housekeeping_tasks",
    )

    objects = TenantScopedManager()

    class Meta:
        app_label = "housekeeping"
        db_table = "housekeeping_task"
        constraints = [
            models.UniqueConstraint(
                fields=["room", "business_date", "task_kind"],
                name="hk_task_uq_room_date_kind",
            ),
            status_constraint("task_kind", TaskKind, "hk_task_valid_kind"),
            status_constraint("status", TaskStatus, "hk_task_valid_status"),
        ]
        indexes = [
            models.Index(
                fields=["assignee", "status", "business_date"], name="hk_task_ix_assignee"
            ),
            models.Index(fields=["property", "business_date"], name="hk_task_ix_property_date"),
            models.Index(fields=["room", "business_date"], name="hk_task_ix_room_date"),
            # R0.9: HousekeepingTaskListView's `?status=` filter (with no
            # `room_id`) — the "what needs attention" query real staff use —
            # matched no index as a leading column; the three above all lead
            # with assignee/property/room. Matches the view's actual filter
            # (status) + order_by (business_date) together.
            models.Index(fields=["status", "-business_date"], name="hk_task_ix_status_date"),
        ]

    def __str__(self) -> str:
        return f"{self.room_id}:{self.business_date} {self.task_kind} ({self.status})"

    # ------------------------------------------------------------------
    # State machine (M12 ruling): planned/assigned -> in_progress ->
    # quality_check -> {verified, defect}. Every transition here is fired
    # ALONGSIDE the corresponding Room transition, in the same
    # HousekeepingService call — never independently (see services.py).
    # ------------------------------------------------------------------

    @workflow_transition(
        field="status", source=TaskStatus.PLANNED, target=TaskStatus.ASSIGNED, event=None
    )
    def assign(self):
        """A housekeeper is assigned before starting (optional step)."""

    @workflow_transition(
        field="status",
        source=[TaskStatus.PLANNED, TaskStatus.ASSIGNED],
        target=TaskStatus.IN_PROGRESS,
        event=None,
    )
    def start_cleaning(self):
        """Cleaning begins. ``planned -> in_progress`` is explicitly
        allowed (unassigned cleaning may start, M12 ruling)."""

    @workflow_transition(
        field="status",
        source=TaskStatus.IN_PROGRESS,
        target=TaskStatus.QUALITY_CHECK,
        event="hk.task_completed",
    )
    def complete_cleaning(self):
        """Cleaning done; awaiting inspection."""

    @workflow_transition(
        field="status", source=TaskStatus.QUALITY_CHECK, target=TaskStatus.VERIFIED, event=None
    )
    def pass_inspection(self):
        """Inspection passed — terminal, successful state."""

    @workflow_transition(
        field="status",
        source=TaskStatus.QUALITY_CHECK,
        target=TaskStatus.DEFECT,
        event="hk.defect_reported",
    )
    def fail_inspection(self):
        """Inspection failed — terminal for THIS task (DDS UQ on
        Inspection: one verdict per task, ever); the room goes back to
        CLEANING via a NEW task, not a loop within this one."""


class InspectionResult(models.TextChoices):
    PASS = "pass", "Pass"
    FAIL = "fail", "Fail"


class Inspection(TimeStampedMixin):
    """The immutable pass/fail verdict for one task (DDS S13). Never
    updated after creation — one row per task, ever (UniqueConstraint)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.RESTRICT, related_name="inspections"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.RESTRICT, related_name="inspections"
    )
    housekeeping_task = models.ForeignKey(
        HousekeepingTask, on_delete=models.RESTRICT, related_name="inspections"
    )
    inspector = models.ForeignKey(
        "accounts.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inspections_performed",
    )
    result = models.CharField(max_length=8, choices=InspectionResult.choices)

    objects = TenantScopedManager()

    class Meta:
        app_label = "housekeeping"
        db_table = "inspection"
        constraints = [
            models.UniqueConstraint(
                fields=["housekeeping_task"], name="inspection_uq_housekeeping_task"
            ),
            status_constraint("result", InspectionResult, "inspection_valid_result"),
        ]

    def __str__(self) -> str:
        return f"task={self.housekeeping_task_id} result={self.result}"
