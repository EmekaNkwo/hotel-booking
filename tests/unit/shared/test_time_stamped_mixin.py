"""Unit tests for the TimeStampedMixin abstract base.

Django model tests adapt the M1.1 ordering:
creation → field invariants → lifecycle behavior → edge cases.
An abstract base needs a concrete child, so a StampProbe model is defined here
and its table is created at module scope via schema_editor.
"""

import time

import pytest
from django import forms
from django.db import connection, models
from django.utils import timezone

from apps.shared.models import TimeStampedMixin


class StampProbe(TimeStampedMixin):
    """Concrete child of the mixin, used only by these tests."""
    label = models.CharField(max_length=50)

    class Meta:
        app_label = "shared"


def _ensure_table(model):
    """Create the probe table only if it does not already exist.

    Django's test-database setup may create tables for registered models, so
    creation must be idempotent to survive any fixture/DB-setup ordering.
    """
    if model._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(model)


@pytest.fixture(scope="module")
def stamp_probe(django_db_blocker):
    """Create the probe table once, outside any test transaction.

    SQLite's schema editor cannot run DDL inside a transaction, so the table is
    created at module scope via django_db_blocker; each transactional test then
    uses it normally and rolls back only its rows. Yields the model class.
    """
    with django_db_blocker.unblock():
        _ensure_table(StampProbe)
    yield StampProbe
    with django_db_blocker.unblock():
        if StampProbe._meta.db_table in connection.introspection.table_names():
            with connection.schema_editor() as editor:
                editor.delete_model(StampProbe)


class TestCreation:
    @pytest.mark.django_db
    def test_sets_both_stamps_on_create(self, stamp_probe):
        probe = stamp_probe.objects.create(label="deluxe")

        assert probe.created_at is not None
        assert probe.updated_at is not None

    @pytest.mark.django_db
    def test_stamps_are_timezone_aware(self, stamp_probe):
        probe = stamp_probe.objects.create(label="deluxe")

        assert timezone.is_aware(probe.created_at)
        assert timezone.is_aware(probe.updated_at)

    @pytest.mark.django_db
    def test_created_and_updated_coincide_at_creation(self, stamp_probe):
        probe = stamp_probe.objects.create(label="deluxe")

        assert probe.updated_at >= probe.created_at


class TestFieldInvariants:
    def test_mixin_declares_both_fields(self):
        assert StampProbe._meta.get_field("created_at") is not None
        assert StampProbe._meta.get_field("updated_at") is not None

    def test_fields_are_non_editable(self):
        assert StampProbe._meta.get_field("created_at").editable is False
        assert StampProbe._meta.get_field("updated_at").editable is False

    def test_mixin_is_abstract(self):
        assert TimeStampedMixin._meta.abstract is True

    def test_no_stamp_table_is_created_for_the_base_itself(self):
        # An abstract base never materializes as its own table.
        assert StampProbe._meta.db_table == "shared_stampprobe"


class TestLifecycle:
    @pytest.mark.django_db
    def test_updated_at_advances_created_at_stays(self, stamp_probe):
        probe = stamp_probe.objects.create(label="deluxe")
        created = probe.created_at

        time.sleep(0.01)
        probe.label = "standard"
        probe.save()
        probe.refresh_from_db()

        assert probe.created_at == created
        assert probe.updated_at > created

    @pytest.mark.django_db
    def test_created_at_ignores_a_manual_value(self, stamp_probe):
        # auto_now_add preempts any supplied value — the stamp is unforgeable.
        old = timezone.now() - timezone.timedelta(days=1)
        probe = stamp_probe.objects.create(label="deluxe", created_at=old)

        probe.refresh_from_db()
        assert probe.created_at != old


class TestEdgeCases:
    @pytest.mark.django_db
    def test_bulk_update_does_not_refresh_updated_at(self, stamp_probe):
        # The documented caveat: QuerySet.update() bypasses save()/auto_now.
        probe = stamp_probe.objects.create(label="deluxe")
        before = probe.updated_at

        time.sleep(0.01)
        stamp_probe.objects.filter(id=probe.id).update(label="changed")
        probe.refresh_from_db()

        assert probe.updated_at == before

    @pytest.mark.django_db
    def test_stamps_are_excluded_from_model_forms(self, stamp_probe):
        class ProbeForm(forms.ModelForm):
            class Meta:
                model = stamp_probe
                fields = "__all__"

        form = ProbeForm()
        assert "created_at" not in form.fields
        assert "updated_at" not in form.fields
