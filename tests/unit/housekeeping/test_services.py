"""HousekeepingService unit tests (M12).

Unit tier: SQLite. The optimistic-locking/race proof is Postgres-only
(tests/integration/test_housekeeping_postgres.py) — this tier proves the
happy path, guards, the FSM matrix, idempotency, and event emission.
"""

import pytest
from django.db import IntegrityError

from apps.bookings.models import BookingStatus
from apps.housekeeping.models import HousekeepingTask, Inspection, InspectionResult, TaskStatus
from apps.housekeeping.services import (
    HousekeepingQuery,
    HousekeepingService,
    TaskNotTransitionable,
)
from apps.rooms.models import Room
from apps.rooms.services import RoomStateMachine
from apps.shared.exceptions import ConcurrencyError, TransitionNotAllowed


@pytest.mark.django_db
class TestCheckOutAndCreateTask:
    def test_checks_out_the_line_and_transitions_room(self, tenant, checked_in_line):
        task = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=checked_in_line.id,
            idempotency_key="co-1",
        )
        checked_in_line.refresh_from_db()
        assert checked_in_line.status == BookingStatus.CHECKED_OUT
        assert task.room_id == checked_in_line.room_id
        assert task.status == TaskStatus.PLANNED
        room = Room.objects.get(pk=checked_in_line.room_id)
        assert room.operational_state == Room.OperationalState.VACANT_DIRTY

    def test_requires_checked_in_status(self, tenant, checked_in_line):
        HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=checked_in_line.id,
            idempotency_key="co-1",
        )
        with pytest.raises(TaskNotTransitionable):
            HousekeepingService.check_out_and_create_task(
                tenant_id=tenant.id,
                booking_line_id=checked_in_line.id,
                idempotency_key="co-2",
            )

    def test_is_idempotent_per_key(self, tenant, checked_in_line):
        first = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=checked_in_line.id,
            idempotency_key="same-key",
        )
        second = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=checked_in_line.id,
            idempotency_key="same-key",
        )
        assert first.id == second.id
        assert HousekeepingTask.objects.count() == 1

    def test_duplicate_departure_task_rejected_at_db_level(self, tenant, checked_in_line):
        """Direct ORM bypass — only the UniqueConstraint can catch a
        duplicate (room, business_date, task_kind)."""
        task = HousekeepingService.check_out_and_create_task(
            tenant_id=tenant.id,
            booking_line_id=checked_in_line.id,
            idempotency_key="co-1",
        )
        with pytest.raises(IntegrityError):
            HousekeepingTask.objects.create(
                tenant=tenant,
                property=task.property,
                room=task.room,
                business_date=task.business_date,
                task_kind=task.task_kind,
            )


@pytest.mark.django_db
class TestCleanAndInspectHappyPath:
    def test_full_pass_cycle_reaches_vacant_clean(self, tenant, departure_task):
        room = departure_task.room
        task = HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.CLEANING
        assert task.status == TaskStatus.IN_PROGRESS

        task = HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=task.id,
            idempotency_key="cc-1",
        )
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.INSPECTED
        assert task.status == TaskStatus.QUALITY_CHECK

        task = HousekeepingService.inspect(
            tenant_id=tenant.id,
            task_id=task.id,
            result="pass",
            idempotency_key="in-1",
        )
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.VACANT_CLEAN
        assert task.status == TaskStatus.VERIFIED
        assert Inspection.objects.get(housekeeping_task=task).result == InspectionResult.PASS

    def test_failed_inspection_sends_room_back_to_cleaning(self, tenant, departure_task):
        room = departure_task.room
        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        task = HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="cc-1",
        )
        task = HousekeepingService.inspect(
            tenant_id=tenant.id,
            task_id=task.id,
            result="fail",
            idempotency_key="in-1",
        )
        room.refresh_from_db()
        assert room.operational_state == Room.OperationalState.CLEANING
        assert task.status == TaskStatus.DEFECT
        assert Inspection.objects.get(housekeeping_task=task).result == InspectionResult.FAIL

    def test_cannot_approve_before_complete_cleaning(self, tenant, departure_task):
        room = departure_task.room
        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        room.refresh_from_db()
        with pytest.raises(TransitionNotAllowed):
            RoomStateMachine.apply(room, "approve")

    def test_cannot_reach_vacant_clean_by_skipping_inspection(self, tenant, departure_task):
        """Room's own FSM guard (M3, unmodified) is what actually enforces
        this — the test locks in that guarantee rather than re-implementing
        it (M12's review-gate proof)."""
        room = departure_task.room
        with pytest.raises(TransitionNotAllowed):
            RoomStateMachine.apply(room, "approve")  # still VACANT_DIRTY

        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        room.refresh_from_db()
        with pytest.raises(TransitionNotAllowed):
            RoomStateMachine.apply(room, "approve")  # CLEANING, not INSPECTED yet

    def test_start_cleaning_requires_planned_or_assigned(self, tenant, departure_task):
        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        with pytest.raises(TaskNotTransitionable):
            HousekeepingService.start_cleaning(
                tenant_id=tenant.id,
                task_id=departure_task.id,
                idempotency_key="sc-2",
            )

    def test_inspect_requires_quality_check_status(self, tenant, departure_task):
        with pytest.raises(TaskNotTransitionable):
            HousekeepingService.inspect(
                tenant_id=tenant.id,
                task_id=departure_task.id,
                result="pass",
                idempotency_key="in-1",
            )

    def test_inspect_rejects_invalid_result(self, tenant, departure_task):
        with pytest.raises(ValueError):
            HousekeepingService.inspect(
                tenant_id=tenant.id,
                task_id=departure_task.id,
                result="maybe",
                idempotency_key="in-1",
            )

    def test_second_inspection_rejected_at_db_level(self, tenant, departure_task):
        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="cc-1",
        )
        task = HousekeepingService.inspect(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            result="pass",
            idempotency_key="in-1",
        )
        with pytest.raises(IntegrityError):
            Inspection.objects.create(
                tenant=tenant,
                property=task.property,
                housekeeping_task=task,
                result="pass",
            )


@pytest.mark.django_db
class TestAssign:
    def test_planned_to_assigned(self, tenant, departure_task):
        task = HousekeepingService.assign(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            assignee=None,
            idempotency_key="a-1",
        )
        assert task.status == TaskStatus.ASSIGNED

    def test_unassigned_start_cleaning_allowed_from_planned(self, tenant, departure_task):
        """M12 ruling: planned -> in_progress is explicitly allowed."""
        task = HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        assert task.status == TaskStatus.IN_PROGRESS


@pytest.mark.django_db
class TestOptimisticConcurrency:
    def test_stale_task_save_raises_concurrency_error(self, tenant, departure_task):
        """Two in-memory copies of the same task; the second save() must
        lose (VersionedMixin, M12's authoritative task-locking mechanism)."""
        stale = HousekeepingTask.objects.get(pk=departure_task.id)
        HousekeepingService.assign(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            assignee=None,
            idempotency_key="a-1",
        )
        stale.assignee = None
        with pytest.raises(ConcurrencyError):
            from apps.shared.workflows.runner import WorkflowRunner

            WorkflowRunner(stale, field="status").run("assign")


@pytest.mark.django_db
class TestEventEmission:
    def test_complete_cleaning_emits_hk_task_completed(self, tenant, departure_task):
        from apps.shared.models import OutboxEvent

        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="cc-1",
        )
        assert OutboxEvent.objects.filter(
            event_type="hk.task_completed", aggregate_id=str(departure_task.id)
        ).exists()

    def test_defect_reported_only_on_failed_inspection(self, tenant, departure_task):
        from apps.shared.models import OutboxEvent

        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="cc-1",
        )
        assert not OutboxEvent.objects.filter(event_type="hk.defect_reported").exists()

        HousekeepingService.inspect(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            result="fail",
            idempotency_key="in-1",
        )
        assert OutboxEvent.objects.filter(
            event_type="hk.defect_reported", aggregate_id=str(departure_task.id)
        ).exists()

    def test_room_state_changed_fires_on_every_room_transition(self, tenant, departure_task):
        from apps.shared.models import OutboxEvent

        room_id = departure_task.room_id
        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="sc-1",
        )
        assert (
            OutboxEvent.objects.filter(
                event_type="room.state_changed", aggregate_id=str(room_id)
            ).count()
            >= 2
        )  # at least checkout + clean by this point


@pytest.mark.django_db
class TestHousekeepingQuery:
    def test_by_room(self, tenant, departure_task):
        assert list(HousekeepingQuery.by_room(departure_task.room)) == [departure_task]

    def test_for_property_and_date(self, tenant, property, departure_task):
        results = HousekeepingQuery.for_property_and_date(property, departure_task.business_date)
        assert list(results) == [departure_task]

    def test_open_tasks_for_assignee_excludes_terminal_states(self, tenant, departure_task):
        from apps.accounts.models import UserAccount

        user = UserAccount.objects.create_user(email="hk@example.com", password="x")
        task = HousekeepingService.assign(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            assignee=user,
            idempotency_key="a-1",
        )
        assert list(HousekeepingQuery.open_tasks_for_assignee(user)) == [task]

        HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=task.id,
            idempotency_key="sc-1",
        )
        HousekeepingService.complete_cleaning(
            tenant_id=tenant.id,
            task_id=task.id,
            idempotency_key="cc-1",
        )
        HousekeepingService.inspect(
            tenant_id=tenant.id,
            task_id=task.id,
            result="pass",
            idempotency_key="in-1",
        )
        assert HousekeepingQuery.open_tasks_for_assignee(user).count() == 0


@pytest.mark.django_db
class TestWorkflowStateGuard:
    """R0.6 regression: ``status`` is WorkflowRunner-governed —
    ``WorkflowStateGuardMixin`` must reject a direct save() bypass, the
    same protection ``Room.operational_state`` has had since M3."""

    def test_direct_status_mutation_is_rejected(self, departure_task):
        departure_task.status = TaskStatus.VERIFIED
        with pytest.raises(ValueError, match="WorkflowRunner"):
            departure_task.save()
        departure_task.refresh_from_db()
        assert departure_task.status == TaskStatus.PLANNED

    def test_saving_unrelated_fields_without_a_status_change_is_allowed(self, departure_task):
        original_kind = departure_task.task_kind
        departure_task.save()  # re-save, same status — must not raise
        departure_task.refresh_from_db()
        assert departure_task.task_kind == original_kind
        assert departure_task.status == TaskStatus.PLANNED

    def test_workflowrunner_driven_transition_still_succeeds(self, tenant, departure_task):
        updated = HousekeepingService.start_cleaning(
            tenant_id=tenant.id,
            task_id=departure_task.id,
            idempotency_key="guard-sc-1",
        )
        assert updated.status == TaskStatus.IN_PROGRESS
