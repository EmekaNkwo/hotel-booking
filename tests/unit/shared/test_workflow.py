"""Unit tests for the WorkflowRunner substrate over django-fsm (M1.6, DR-07).

Order: declared transitions → guards → permissions → the substrate contract
(state change + outbox event + audit row in ONE transaction) → atomic rollback
→ edge cases. The probe workflow models live under the non-migrated "probes"
app; their tables are created idempotently at module scope.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, models
from django_fsm import FSMField

from apps.shared.exceptions import AppendOnlyViolation
from apps.shared.models import AuditLog, DomainEvent, EntityMixin, OutboxEvent
from apps.shared.workflows.runner import WorkflowRunner, workflow_transition

TENANT = 7


def _guard_deposit_paid(instance):
    return instance.deposit_paid


class BookingWorkflowProbe(EntityMixin):
    # protected=False (django-fsm default): the ORM must be able to re-set
    # state on refresh_from_db(). Transition-only discipline is enforced by the
    # runner — the single public path that changes state — not by the field.
    state = FSMField(default="pending")
    deposit_paid = models.BooleanField(default=False)

    class Meta:
        app_label = "probes"

    @workflow_transition(source="pending", target="confirmed", event="booking.confirmed")
    def confirm(self):
        pass

    @workflow_transition(
        source="confirmed",
        target="cancelled",
        event="booking.cancelled",
        conditions=[_guard_deposit_paid],
    )
    def cancel(self):
        pass

    @workflow_transition(source="confirmed", target="archived", event=None)
    def archive(self):
        pass

    @workflow_transition(
        source="pending", target="blocked", permission=lambda instance, user: False
    )
    def block(self):
        pass


def _ensure_table(model):
    if model._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(model)


@pytest.fixture(scope="module")
def workflow_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(BookingWorkflowProbe)
    yield BookingWorkflowProbe


def _purge(model):
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {model._meta.db_table}")


@pytest.fixture(autouse=True)
def _clean():
    yield
    _purge(BookingWorkflowProbe)
    _purge(OutboxEvent)
    _purge(DomainEvent)
    _purge(AuditLog)


class TestDeclaredTransitions:
    @pytest.mark.django_db
    def test_lists_all_declared_transitions(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        runner = WorkflowRunner(booking)

        assert set(runner.transitions()) == {"confirm", "cancel", "archive", "block"}

    @pytest.mark.django_db
    def test_available_transitions_respect_current_state(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        runner = WorkflowRunner(booking)

        # source-eligible + guards pass (permission not checked here):
        assert set(runner.available()) == {"confirm", "block"}
        # full check — can_run also evaluates permission:
        assert runner.can_run("confirm") is True
        assert runner.can_run("cancel") is False  # cancel needs state=confirmed
        assert runner.can_run("block") is False  # permission denies


class TestGuards:
    @pytest.mark.django_db
    def test_guard_failure_makes_transition_unavailable(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT, deposit_paid=False)
        runner = WorkflowRunner(booking)
        runner.run("confirm")

        # deposit not paid → the cancel guard fails → not available.
        assert runner.can_run("cancel") is False

    @pytest.mark.django_db
    def test_guard_pass_makes_transition_available(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT, deposit_paid=True)
        runner = WorkflowRunner(booking)
        runner.run("confirm")

        assert runner.can_run("cancel") is True


class TestPermissions:
    @pytest.mark.django_db
    def test_permission_denial_blocks_the_transition(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        runner = WorkflowRunner(booking)

        # The block transition declares a permission callable that always
        # denies; the substrate surfaces it as unavailable (django-fsm checks
        # permission in can_proceed even without an explicit user context).
        assert runner.can_run("block") is False
        with pytest.raises(Exception) as exc_info:
            runner.run("block")
        assert exc_info.type.__name__ == "TransitionNotAllowed"


class TestSubstrateContract:
    @pytest.mark.django_db
    def test_run_changes_state_and_emits_event_and_audit_together(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        actor = get_user_model().objects.create_user(username="desk-agent")
        runner = WorkflowRunner(booking)

        result = runner.run("confirm", actor=actor, reason="guest confirmed")

        assert result.state == "confirmed"
        # One outbox row for the declared event.
        row = OutboxEvent.objects.get()
        assert row.event_type == "booking.confirmed"
        assert row.payload == {"from": "pending", "to": "confirmed"}
        # Exactly one audit row — audit is always on, actor recorded by FK.
        entry = AuditLog.objects.get()
        assert entry.action == "confirm"
        assert entry.before == {"state": "pending"}
        assert entry.after == {"state": "confirmed"}
        assert entry.reason == "guest confirmed"
        assert entry.actor_id == actor.pk

    @pytest.mark.django_db
    def test_transition_without_event_emits_no_outbox_row(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        runner = WorkflowRunner(booking)
        runner.run("confirm")
        runner.run("archive", reason="housekeeping")

        assert booking.state == "archived"
        assert OutboxEvent.objects.count() == 1  # only confirm emitted one
        assert AuditLog.objects.count() == 2  # but every transition audited

    @pytest.mark.django_db
    def test_state_transition_is_persisted(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        WorkflowRunner(booking).run("confirm")

        booking.refresh_from_db()
        assert booking.state == "confirmed"
        assert booking.version == 1  # EntityMixin save bumped the version


class TestAtomicity:
    @pytest.mark.django_db(transaction=True)
    def test_undefined_transition_raises_and_writes_nothing(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        runner = WorkflowRunner(booking)

        with pytest.raises(Exception) as exc_info:
            runner.run("no_such_transition")
        assert exc_info.type.__name__ == "TransitionNotAllowed"

        assert OutboxEvent.objects.count() == 0
        assert AuditLog.objects.count() == 0
        booking.refresh_from_db()
        assert booking.state == "pending"

    @pytest.mark.django_db(transaction=True)
    def test_unavailable_transition_raises_and_writes_nothing(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        runner = WorkflowRunner(booking)
        runner.run("confirm")

        with pytest.raises(Exception) as exc_info:
            runner.run("confirm")  # already confirmed — no longer available
        assert exc_info.type.__name__ == "TransitionNotAllowed"

        assert OutboxEvent.objects.count() == 1  # the first run's only
        assert AuditLog.objects.count() == 1


class TestEdgeCases:
    @pytest.mark.django_db
    def test_audit_entries_and_events_are_immutable(self, workflow_probe):
        booking = workflow_probe.objects.create(tenant_id=TENANT)
        WorkflowRunner(booking).run("confirm")

        audit = AuditLog.objects.get()
        with pytest.raises(AppendOnlyViolation):
            audit.save()

        # The confirm run wrote an outbox row; the relay promotes it to the
        # immutable DomainEvent log.
        from apps.shared.services.outbox import OutboxRelay

        OutboxRelay().publish_batch()
        event = DomainEvent.objects.get()
        with pytest.raises(AppendOnlyViolation):
            event.save()
