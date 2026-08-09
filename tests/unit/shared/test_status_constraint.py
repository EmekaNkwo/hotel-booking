"""Unit tests for the TextChoices + CheckConstraint recipe (E3).

Order follows the M1.2 adaptation:
recipe mechanics → domain (TextChoices) → ORM/form layer → database layer → edge cases.
"""

import pytest
from django import forms
from django.db import IntegrityError, connection, models, transaction

from apps.shared.models import status_constraint


class ProbeStatus(models.TextChoices):
    """An illustrative closed set — real statuses belong to their contexts (M3/M9)."""
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"


class StatusProbe(models.Model):
    """The recipe applied: TextChoices field + CheckConstraint in Meta."""
    status = models.CharField(
        max_length=20, choices=ProbeStatus.choices, default=ProbeStatus.PENDING
    )

    class Meta:
        app_label = "probes"
        constraints = [status_constraint("status", ProbeStatus, "statusprobe_status_valid")]


class NoConstraintProbe(models.Model):
    """The control: same field, NO constraint — proves choices= alone is form-only."""
    status = models.CharField(
        max_length=20, choices=ProbeStatus.choices, default=ProbeStatus.PENDING
    )

    class Meta:
        app_label = "probes"


def _ensure_table(probe):
    """Create the probe table only if it does not already exist.

    Django's test-database setup may create tables for registered models, so
    creation must be idempotent to survive any fixture/DB-setup ordering.
    """
    if probe._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(probe)


@pytest.fixture(scope="module")
def status_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(StatusProbe)
    yield StatusProbe


@pytest.fixture(scope="module")
def no_constraint_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(NoConstraintProbe)
    yield NoConstraintProbe


class TestRecipe:
    def test_status_constraint_builds_a_check_constraint(self):
        constraint = status_constraint("status", ProbeStatus, "probe_valid")

        assert isinstance(constraint, models.CheckConstraint)
        assert constraint.name == "probe_valid"

    def test_the_probe_model_registers_the_constraint(self):
        names = {c.name for c in StatusProbe._meta.constraints}

        assert "statusprobe_status_valid" in names

    def test_the_choices_class_exposes_the_closed_set(self):
        assert tuple(ProbeStatus.values) == ("pending", "confirmed", "cancelled")


class TestDomain:
    def test_members_are_str_subclasses_with_labels(self):
        assert str(ProbeStatus.CONFIRMED) == "confirmed"
        assert ProbeStatus.CONFIRMED.label == "Confirmed"
        assert ProbeStatus.CONFIRMED == "confirmed"  # works as a plain string value


class TestOrmAndFormLayer:
    def test_choices_are_enforced_at_the_form_level(self):
        class StatusForm(forms.ModelForm):
            class Meta:
                model = StatusProbe
                fields = "__all__"

        form = StatusForm(data={"status": "half-occupied"})

        assert "status" in form.errors

    @pytest.mark.django_db
    def test_choices_are_not_enforced_by_create(self, no_constraint_probe):
        # The trap the recipe closes: without a CheckConstraint, create() stores
        # whatever string it is given — choices= never ran.
        row = no_constraint_probe.objects.create(status="half-occupied")

        assert row.status == "half-occupied"


class TestDatabaseLayer:
    @pytest.mark.django_db
    def test_valid_status_is_accepted(self, status_probe):
        row = status_probe.objects.create(status=ProbeStatus.CONFIRMED)

        assert row.status == "confirmed"

    @pytest.mark.django_db
    def test_default_applies_on_create(self, status_probe):
        row = status_probe.objects.create()

        assert row.status == "pending"

    @pytest.mark.django_db
    def test_invalid_status_is_blocked_at_the_database(self, status_probe):
        # The payoff: create() skips choices= validation, but the constraint is
        # in the schema — the INSERT itself fails.
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                status_probe.objects.create(status="half-occupied")

    @pytest.mark.django_db
    def test_bulk_create_is_also_blocked(self, status_probe):
        # bulk_create bypasses save() and forms entirely; only the schema holds.
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                status_probe.objects.bulk_create(
                    [status_probe(status="half-occupied")]
                )
