"""Unit tests for the Tenant root (M2.1, DMS §2, SDD §13.4).

Order: creation → lifecycle status → schema constraints (ISO3 currency, status
closed set) → optimistic locking. Tenant is platform-scoped: no tenant_id.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.shared.exceptions import ConcurrencyError
from apps.tenants.models import Tenant, TenantStatus


@pytest.fixture(autouse=True)
def _clean():
    yield
    Tenant.objects.all().delete()


class TestCreation:
    @pytest.mark.django_db
    def test_creates_a_tenant_with_currency_and_code(self):
        tenant = Tenant.objects.create(code="acme", name="Acme Hotels", base_currency="NGN")

        assert tenant.code == "acme"
        assert tenant.name == "Acme Hotels"
        assert tenant.base_currency == "NGN"
        assert tenant.status == TenantStatus.PROSPECTIVE

    @pytest.mark.django_db
    def test_code_is_unique_platform_wide(self):
        Tenant.objects.create(code="acme", name="A", base_currency="NGN")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Tenant.objects.create(code="acme", name="B", base_currency="NGN")


class TestLifecycle:
    @pytest.mark.django_db
    def test_status_transitions_are_data(self):
        tenant = Tenant.objects.create(code="acme", name="A", base_currency="NGN")
        tenant.status = TenantStatus.ACTIVE
        tenant.save()

        tenant.refresh_from_db()
        assert tenant.status == TenantStatus.ACTIVE
        assert tenant.version == 1


class TestConstraints:
    @pytest.mark.django_db
    def test_currency_must_be_iso3(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Tenant.objects.create(code="bad", name="A", base_currency="nG")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Tenant.objects.create(code="bad2", name="B", base_currency="EURO")

    @pytest.mark.django_db
    def test_invalid_status_is_blocked(self):
        tenant = Tenant.objects.create(code="acme", name="A", base_currency="NGN")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Tenant.objects.filter(pk=tenant.pk).update(status="half-open")


class TestOptimisticLocking:
    @pytest.mark.django_db
    def test_stale_save_raises_concurrency_error(self):
        tenant = Tenant.objects.create(code="acme", name="A", base_currency="NGN")
        desk_a = Tenant.objects.get(pk=tenant.pk)
        desk_b = Tenant.objects.get(pk=tenant.pk)

        desk_a.name = "Renamed by A"
        desk_a.save()

        desk_b.name = "Renamed by B"
        with pytest.raises(ConcurrencyError):
            desk_b.save()
