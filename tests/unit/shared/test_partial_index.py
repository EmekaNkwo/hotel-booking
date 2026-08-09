"""Unit tests for the partial-index recipe and migrations discipline.

Order follows the M1.2 adaptation:
recipe mechanics → schema validity → contrast with a full index →
migrations discipline → edge cases.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection, models

from apps.shared.models import partial_index


class SweepProbe(models.Model):
    """The recipe applied: a partial index over the hot 'pending' subset."""
    status = models.CharField(max_length=20, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "probes"
        indexes = [
            partial_index(
                ["created_at"],
                models.Q(status="pending"),
                "sweepprobe_pending_created",
            ),
        ]


def _ensure_table(model):
    if model._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(model)


@pytest.fixture(scope="module")
def sweep_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(SweepProbe)
    yield SweepProbe  # the model class, whose table now exists


class TestRecipe:
    def test_builds_a_conditional_index(self):
        index = partial_index(
            ["created_at"], models.Q(status="pending"), "idx_pending_created"
        )

        assert isinstance(index, models.Index)
        assert index.name == "idx_pending_created"
        assert index.fields == ["created_at"]
        assert index.condition == models.Q(status="pending")

    def test_condition_targets_the_hot_subset(self):
        index = partial_index(["created_at"], models.Q(status="pending"), "idx")

        assert ("status", "pending") in index.condition.children

    def test_the_probe_model_registers_it(self):
        names = {i.name for i in SweepProbe._meta.indexes}

        assert "sweepprobe_pending_created" in names

    def test_a_full_index_has_no_condition(self):
        # The contrast: a normal index covers every row; the partial one is
        # restricted by a WHERE. The recipe is what adds the restriction.
        full = models.Index(name="idx_full", fields=["created_at"])

        assert full.condition is None


class TestSchemaValidity:
    @pytest.mark.django_db
    def test_creating_the_table_applies_the_partial_index(self, sweep_probe):
        # Proves the recipe yields valid, realizable schema on the engine.
        assert sweep_probe._meta.db_table == "probes_sweepprobe"
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, "probes_sweepprobe"
            )

        assert "sweepprobe_pending_created" in constraints
        assert constraints["sweepprobe_pending_created"]["index"]


class TestMigrationsDiscipline:
    @pytest.mark.django_db
    def test_models_and_migrations_are_in_sync(self):
        # The no-drift invariant: if a model changed without a migration,
        # makemigrations --check reports it and exits non-zero. (The DB is
        # needed because makemigrations cross-checks django_migrations history.)
        out = StringIO()
        call_command("makemigrations", "--check", "--dry-run", stdout=out)

        assert "No changes detected" in out.getvalue()

    def test_probe_models_are_abstracted_away_from_migrations(self):
        # Test-only models register under the non-migrated "probes" app, never
        # under "shared", so they cannot create pending migrations — the
        # platform stays drift-free even though probe tables exist in the test DB.
        assert SweepProbe._meta.app_label == "probes"
        assert SweepProbe._meta.db_table == "probes_sweepprobe"
