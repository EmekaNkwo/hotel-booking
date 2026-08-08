"""Unit tests for TenantScopedMixin, VersionedMixin and EntityMixin.

Order follows the M1.2 adaptation:
ownership (tenant scoping) → versioning mechanics → concurrency protection →
composition → edge cases. An abstract base needs concrete children, so probe
models are defined here and their tables created idempotently at module scope.
"""

import pytest
from django import forms
from django.db import IntegrityError, connection, models, transaction

from apps.shared.exceptions import ConcurrencyError
from apps.shared.models import EntityMixin, TenantScopedMixin, VersionedMixin


class TenantProbe(TenantScopedMixin):
    label = models.CharField(max_length=50)

    class Meta:
        app_label = "shared"


class VersionProbe(VersionedMixin):
    label = models.CharField(max_length=50)

    class Meta:
        app_label = "shared"


class EntityProbe(EntityMixin):
    label = models.CharField(max_length=50)

    class Meta:
        app_label = "shared"


def _ensure_table(model):
    if model._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(model)


@pytest.fixture(scope="module")
def tenant_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(TenantProbe)
    yield TenantProbe


@pytest.fixture(scope="module")
def version_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(VersionProbe)
    yield VersionProbe


@pytest.fixture(scope="module")
def entity_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(EntityProbe)
    yield EntityProbe


class TestTenantScoping:
    @pytest.mark.django_db
    def test_requires_tenant_id_on_create(self, tenant_probe):
        # Ownership is never optional — a row without a tenant cannot exist.
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                tenant_probe.objects.create(label="orphan")

    @pytest.mark.django_db
    def test_stores_the_tenant(self, tenant_probe):
        row = tenant_probe.objects.create(tenant_id=7, label="deluxe")

        assert row.tenant_id == 7

    def test_tenant_id_is_indexed(self):
        assert TenantProbe._meta.get_field("tenant_id").db_index is True

    def test_tenant_id_is_non_editable(self):
        assert TenantProbe._meta.get_field("tenant_id").editable is False

    def test_tenant_id_is_a_positive_field(self):
        assert isinstance(
            TenantProbe._meta.get_field("tenant_id"), models.PositiveBigIntegerField
        )


class TestVersioning:
    @pytest.mark.django_db
    def test_version_starts_at_zero(self, version_probe):
        row = version_probe.objects.create(label="a")

        assert row.version == 0

    @pytest.mark.django_db
    def test_save_bumps_version(self, version_probe):
        row = version_probe.objects.create(label="a")

        row.label = "b"
        row.save()
        assert row.version == 1

        row.label = "c"
        row.save()
        assert row.version == 2

    @pytest.mark.django_db
    def test_save_with_update_fields_still_bumps_version(self, version_probe):
        # A bulk .update() does not bump version; a guarded save() does — even
        # when restricted to a subset of fields. 0 -> 1 (bulk leaves it 0).
        row = version_probe.objects.create(label="a")
        version_probe.objects.filter(pk=row.pk).update(label="b")

        fresh = version_probe.objects.get(pk=row.pk)
        fresh.label = "c"
        fresh.save(update_fields=["label"])

        assert version_probe.objects.get(pk=row.pk).version == 1

    def test_version_is_non_editable(self):
        assert VersionProbe._meta.get_field("version").editable is False


class TestConcurrency:
    @pytest.mark.django_db
    def test_stale_save_raises_concurrency_error(self, entity_probe):
        """The lost-update scenario: two writers, one row, two versions."""
        original = entity_probe.objects.create(tenant_id=1, label="base")
        desk_a = entity_probe.objects.get(pk=original.pk)  # reads version 0
        desk_b = entity_probe.objects.get(pk=original.pk)  # reads version 0

        desk_a.label = "confirmed-by-a"
        desk_a.save()  # version 0 -> 1, succeeds

        desk_b.label = "cancelled-by-b"
        with pytest.raises(ConcurrencyError):
            desk_b.save()  # WHERE version=0 matches nothing — detected, not lost

        # The winning write is preserved.
        assert entity_probe.objects.get(pk=original.pk).label == "confirmed-by-a"

    @pytest.mark.django_db
    def test_reload_then_save_recovers(self, entity_probe):
        """The documented recovery path: reload the row and re-apply."""
        original = entity_probe.objects.create(tenant_id=1, label="base")
        desk_a = entity_probe.objects.get(pk=original.pk)
        desk_b = entity_probe.objects.get(pk=original.pk)

        desk_a.label = "a"
        desk_a.save()

        with pytest.raises(ConcurrencyError):
            desk_b.label = "b"
            desk_b.save()

        # Reload picks up version 1; the re-applied write now succeeds.
        desk_b.refresh_from_db()
        desk_b.label = "b"
        desk_b.save()

        assert entity_probe.objects.get(pk=original.pk).label == "b"
        assert entity_probe.objects.get(pk=original.pk).version == 2

    @pytest.mark.django_db
    def test_independent_rows_do_not_conflict(self, entity_probe):
        row_a = entity_probe.objects.create(tenant_id=1, label="a")
        row_b = entity_probe.objects.create(tenant_id=2, label="b")

        row_a.label = "a2"
        row_a.save()
        row_b.label = "b2"
        row_b.save()  # different pk, different version — no conflict

        assert row_b.version == 1


class TestEntityMixin:
    def test_composes_all_three_concerns(self):
        for field in ("created_at", "updated_at", "tenant_id", "version"):
            assert EntityProbe._meta.get_field(field) is not None

    def test_mixin_is_abstract(self):
        assert EntityMixin._meta.abstract is True

    @pytest.mark.django_db
    def test_entity_save_bumps_version_keeps_created_at(self, entity_probe):
        row = entity_probe.objects.create(tenant_id=1, label="a")
        created = row.created_at

        row.label = "b"
        row.save()

        row.refresh_from_db()
        assert row.version == 1
        assert row.created_at == created


class TestEdgeCases:
    @pytest.mark.django_db
    def test_stamps_are_excluded_from_forms(self, entity_probe):
        class ProbeForm(forms.ModelForm):
            class Meta:
                model = entity_probe
                fields = "__all__"

        form = ProbeForm()
        assert "tenant_id" not in form.fields
        assert "version" not in form.fields
