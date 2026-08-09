"""Unit tests for ProjectionState — idempotent consumer checkpoints (M1.6).

ProjectionState is deliberately a mutable checkpoint (TimeStampedMixin only —
not tenant-scoped, no version, not append-only): consumers advance it as they
fold domain events, and it exists so ETL can resume exactly-once after a crash.
"""

import pytest
from django.utils import timezone

from apps.shared.models import ProjectionState, ProjectionStatus


@pytest.fixture(autouse=True)
def _clean():
    yield
    ProjectionState.objects.all().delete()


class TestCheckpoint:
    @pytest.mark.django_db
    def test_projection_name_is_the_primary_key(self):
        row = ProjectionState.objects.create(
            projection_name="search_index",
            last_event_id="42",
            last_processed_at=timezone.now(),
        )

        assert ProjectionState.objects.get(projection_name="search_index").pk == row.pk

    @pytest.mark.django_db
    def test_consumer_advances_the_checkpoint_to_resume(self):
        row = ProjectionState.objects.create(projection_name="timeline")

        row.last_event_id = "event-77"
        row.save()

        row.refresh_from_db()
        assert row.last_event_id == "event-77"

    @pytest.mark.django_db
    def test_status_surfaces_a_failed_consumer(self):
        row = ProjectionState.objects.create(
            projection_name="reporting",
            status=ProjectionStatus.FAILED,
            last_error="projection function crashed",
        )

        assert row.status == ProjectionStatus.FAILED
        assert "crashed" in row.last_error


class TestNotTenantScoped:
    @pytest.mark.django_db  # the autouse _clean fixture touches the DB
    def test_projection_state_has_no_tenant_id(self):
        # Projections aggregate across tenants, so the checkpoint is
        # platform-level — deliberately NOT tenant-scoped.
        names = {f.name for f in ProjectionState._meta.get_fields()}
        assert "tenant_id" not in names
