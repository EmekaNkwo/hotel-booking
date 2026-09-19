"""Housekeeping Engine (M12, SDD S10.3, DDS S13).

Authoritative references:
- SDD S10.3 (housekeeping workflow), S9.3 (Room state machine, reused unmodified)
- DDS S13 — Housekeeping (``housekeeping_task``/``inspection`` schema + locking)
- Implementation roadmap M12

``HousekeepingService`` is the ONLY entry point. Every method that changes
both task state and room state does so in ONE atomic transaction, composing
``RoomStateMachine.apply()`` (M3, unmodified) and ``WorkflowRunner`` (for
``HousekeepingTask``'s own FSM) — never writing ``Room.operational_state``
or ``HousekeepingTask.status`` directly.

Locking (M12 ruling): ``HousekeepingTask`` is OPTIMISTIC
(``VersionedMixin``, via ``EntityMixin``) — NO ``select_for_update()``
anywhere on it. A lost race surfaces as ``ConcurrencyError`` (existing M1
mechanism), exactly like a lost race on ``Room`` itself. ``BookingLine`` in
the checkout orchestration reuses the project's established pessimistic
pattern for that model (``select_for_update()``, matching M11's
``AllocationService``).
"""

from django.utils import timezone

from apps.bookings.models import BookingLine, BookingStatus
from apps.housekeeping.models import (
    HousekeepingTask,
    Inspection,
    InspectionResult,
    TaskKind,
    TaskStatus,
)
from apps.rooms.services import RoomStateMachine
from apps.shared.services.idempotency import IdempotencyService
from apps.shared.workflows.runner import WorkflowRunner


class TaskNotTransitionable(Exception):
    """The task is not in a state this operation can act on — a cheap,
    explicit pre-check ahead of the Room transition (so a doomed call never
    mutates Room before failing), belt-and-suspenders alongside the FSM's
    own guard on the task transition itself."""


class HousekeepingService:
    """The clean -> inspect loop: check-out orchestration, assignment,
    cleaning, and inspection — composing Room's and the task's own FSMs."""

    # ------------------------------------------------------------------
    # check_out_and_create_task() — the departure trigger (M12 S2 ruling)
    # ------------------------------------------------------------------

    @classmethod
    def check_out_and_create_task(
        cls, *, tenant_id: int, booking_line_id: int, idempotency_key: str, actor=None
    ) -> HousekeepingTask:
        """Check the guest's line out and open the departure cleaning task
        — ONE atomic transaction. Does not own booking economics or guest
        data; it only coordinates check-out with the housekeeping workflow.
        """
        request_payload = {"booking_line_id": booking_line_id}

        def _execute() -> dict:
            booking_line = BookingLine.objects.select_for_update().get(pk=booking_line_id)
            if booking_line.status != BookingStatus.CHECKED_IN:
                raise TaskNotTransitionable(
                    f"BookingLine {booking_line_id} is not checked_in "
                    f"(status={booking_line.status!r}) — cannot check out"
                )
            room = booking_line.room
            if room is None:
                raise TaskNotTransitionable(f"BookingLine {booking_line_id} has no assigned room")

            RoomStateMachine.apply(room, "checkout", actor=actor, reason="guest departed")

            booking_line.status = BookingStatus.CHECKED_OUT
            booking_line.save(update_fields=["status", "updated_at"])

            task = HousekeepingTask.objects.create(
                tenant_id=tenant_id,
                property_id=booking_line.booking.property_id,
                room=room,
                booking_line=booking_line,
                business_date=timezone.now().date(),
                task_kind=TaskKind.DEPARTURE,
                status=TaskStatus.PLANNED,
            )
            return {"task_id": task.id}

        response = IdempotencyService(
            tenant_id=tenant_id, scope="housekeeping.check_out_and_create_task"
        ).run(idempotency_key, request_payload, execute=_execute)
        return HousekeepingTask.objects.get(pk=response["task_id"])

    # ------------------------------------------------------------------
    # assign() — optional, before cleaning starts
    # ------------------------------------------------------------------

    @classmethod
    def assign(
        cls, *, tenant_id: int, task_id: int, assignee, idempotency_key: str
    ) -> HousekeepingTask:
        request_payload = {"task_id": task_id, "assignee_id": getattr(assignee, "id", None)}

        def _execute() -> dict:
            task = HousekeepingTask.objects.get(pk=task_id)
            task.assignee = assignee
            WorkflowRunner(task, field="status").run("assign", reason="assigned to housekeeper")
            return {"task_id": task.id}

        response = IdempotencyService(tenant_id=tenant_id, scope="housekeeping.assign").run(
            idempotency_key, request_payload, execute=_execute
        )
        return HousekeepingTask.objects.get(pk=response["task_id"])

    # ------------------------------------------------------------------
    # start_cleaning() — Room VACANT_DIRTY -> CLEANING + task -> in_progress
    # ------------------------------------------------------------------

    @classmethod
    def start_cleaning(
        cls, *, tenant_id: int, task_id: int, idempotency_key: str, actor=None
    ) -> HousekeepingTask:
        request_payload = {"task_id": task_id}

        def _execute() -> dict:
            task = HousekeepingTask.objects.select_related("room").get(pk=task_id)
            if task.status not in (TaskStatus.PLANNED, TaskStatus.ASSIGNED):
                raise TaskNotTransitionable(
                    f"HousekeepingTask {task_id} is not planned/assigned (status={task.status!r})"
                )
            RoomStateMachine.apply(task.room, "clean", actor=actor, reason="cleaning started")
            WorkflowRunner(task, field="status").run("start_cleaning", reason="cleaning started")
            return {"task_id": task.id}

        response = IdempotencyService(tenant_id=tenant_id, scope="housekeeping.start_cleaning").run(
            idempotency_key, request_payload, execute=_execute
        )
        return HousekeepingTask.objects.get(pk=response["task_id"])

    # ------------------------------------------------------------------
    # complete_cleaning() — Room CLEANING -> INSPECTED + task -> quality_check
    # ------------------------------------------------------------------

    @classmethod
    def complete_cleaning(
        cls, *, tenant_id: int, task_id: int, idempotency_key: str, actor=None
    ) -> HousekeepingTask:
        request_payload = {"task_id": task_id}

        def _execute() -> dict:
            task = HousekeepingTask.objects.select_related("room").get(pk=task_id)
            if task.status != TaskStatus.IN_PROGRESS:
                raise TaskNotTransitionable(
                    f"HousekeepingTask {task_id} is not in_progress (status={task.status!r})"
                )
            RoomStateMachine.apply(
                task.room, "complete_cleaning", actor=actor, reason="cleaning complete"
            )
            WorkflowRunner(task, field="status").run(
                "complete_cleaning", reason="cleaning complete; awaiting inspection"
            )
            return {"task_id": task.id}

        response = IdempotencyService(
            tenant_id=tenant_id, scope="housekeeping.complete_cleaning"
        ).run(idempotency_key, request_payload, execute=_execute)
        return HousekeepingTask.objects.get(pk=response["task_id"])

    # ------------------------------------------------------------------
    # inspect() — pass: Room -> VACANT_CLEAN, task -> verified
    #             fail: Room -> CLEANING (reject), task -> defect
    # ------------------------------------------------------------------

    @classmethod
    def inspect(
        cls,
        *,
        tenant_id: int,
        task_id: int,
        result: str,
        idempotency_key: str,
        inspector=None,
        actor=None,
    ) -> HousekeepingTask:
        if result not in (InspectionResult.PASS, InspectionResult.FAIL):
            raise ValueError(f"inspect() result must be 'pass' or 'fail', got {result!r}")

        request_payload = {"task_id": task_id, "result": result}

        def _execute() -> dict:
            task = HousekeepingTask.objects.select_related("room").get(pk=task_id)
            if task.status != TaskStatus.QUALITY_CHECK:
                raise TaskNotTransitionable(
                    f"HousekeepingTask {task_id} is not in quality_check (status={task.status!r})"
                )

            inspection = Inspection.objects.create(
                tenant_id=tenant_id,
                property_id=task.property_id,
                housekeeping_task=task,
                inspector=inspector,
                result=result,
            )

            if result == InspectionResult.PASS:
                RoomStateMachine.apply(
                    task.room, "approve", actor=actor, reason="inspection passed"
                )
                WorkflowRunner(task, field="status").run(
                    "pass_inspection", reason="inspection passed"
                )
            else:
                RoomStateMachine.apply(task.room, "reject", actor=actor, reason="inspection failed")
                WorkflowRunner(task, field="status").run(
                    "fail_inspection", reason="inspection failed"
                )

            return {"task_id": task.id, "inspection_id": inspection.id}

        response = IdempotencyService(tenant_id=tenant_id, scope="housekeeping.inspect").run(
            idempotency_key, request_payload, execute=_execute
        )
        return HousekeepingTask.objects.get(pk=response["task_id"])


class HousekeepingQuery:
    """Read-only selectors over ``housekeeping_task``/``inspection``."""

    @staticmethod
    def by_room(room):
        return HousekeepingTask.objects.filter(room=room).order_by("-business_date")

    @staticmethod
    def for_property_and_date(property, business_date):
        return HousekeepingTask.objects.filter(
            property=property, business_date=business_date
        ).select_related("room", "assignee")

    @staticmethod
    def open_tasks_for_assignee(assignee):
        return HousekeepingTask.objects.filter(assignee=assignee).exclude(
            status__in=[TaskStatus.VERIFIED, TaskStatus.DEFECT]
        )
