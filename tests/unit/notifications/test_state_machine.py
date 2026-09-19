"""NotificationJob state-machine transition matrix (M13).

Exercises the declared edges directly via WorkflowRunner — mirrors
tests/unit/reservations/test_state_machine.py / M12's HousekeepingTask tests.
"""

import pytest

from apps.notifications.models import JobStatus, NotificationJob
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.workflows.runner import WorkflowRunner


@pytest.fixture
def job(tenant):
    return NotificationJob.objects.create(
        tenant=tenant,
        notification_type="reservation_created",
        channel="email",
        status=JobStatus.PENDING,
    )


@pytest.mark.django_db
class TestValidTransitions:
    def test_pending_to_delivering(self, job):
        updated = WorkflowRunner(job, field="status").run("start_delivering")
        assert updated.status == JobStatus.DELIVERING

    def test_delivering_to_delivered(self, job):
        WorkflowRunner(job, field="status").run("start_delivering")
        updated = WorkflowRunner(job, field="status").run("mark_delivered")
        assert updated.status == JobStatus.DELIVERED

    def test_delivering_to_failed(self, job):
        WorkflowRunner(job, field="status").run("start_delivering")
        updated = WorkflowRunner(job, field="status").run("mark_failed")
        assert updated.status == JobStatus.FAILED

    def test_failed_to_delivering_retry(self, job):
        WorkflowRunner(job, field="status").run("start_delivering")
        WorkflowRunner(job, field="status").run("mark_failed")
        updated = WorkflowRunner(job, field="status").run("start_delivering")
        assert updated.status == JobStatus.DELIVERING

    def test_failed_to_dead_lettered(self, job):
        WorkflowRunner(job, field="status").run("start_delivering")
        WorkflowRunner(job, field="status").run("mark_failed")
        updated = WorkflowRunner(job, field="status").run("dead_letter")
        assert updated.status == JobStatus.DEAD_LETTERED


@pytest.mark.django_db
class TestForbiddenTransitions:
    def test_pending_to_delivered_is_not_allowed(self, job):
        with pytest.raises(TransitionNotAllowed):
            WorkflowRunner(job, field="status").run("mark_delivered")

    def test_pending_to_dead_lettered_is_not_allowed(self, job):
        with pytest.raises(TransitionNotAllowed):
            WorkflowRunner(job, field="status").run("dead_letter")

    def test_delivered_is_terminal(self, job):
        WorkflowRunner(job, field="status").run("start_delivering")
        WorkflowRunner(job, field="status").run("mark_delivered")
        for name in ("start_delivering", "mark_delivered", "mark_failed", "dead_letter"):
            with pytest.raises(TransitionNotAllowed):
                WorkflowRunner(job, field="status").run(name)

    def test_dead_lettered_is_terminal(self, job):
        WorkflowRunner(job, field="status").run("start_delivering")
        WorkflowRunner(job, field="status").run("mark_failed")
        WorkflowRunner(job, field="status").run("dead_letter")
        for name in ("start_delivering", "mark_delivered", "mark_failed", "dead_letter"):
            with pytest.raises(TransitionNotAllowed):
                WorkflowRunner(job, field="status").run(name)
