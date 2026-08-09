"""Cross-tenant leakage tests for the app-layer tenant-scoped manager (M2.1).

This is defense-in-depth layer 2 (SDD §13.2): when a request tenant context is
stamped, ``TenantScopedManager.get_queryset()`` auto-filters by it, so a
developer who forgets an explicit filter still cannot read another tenant's
rows. Outside a context the queryset is deliberately unfiltered — cross-tenant
platform work is an explicit ``.unscoped()`` act, never implicit.

These tests drive the tenancy context directly (the middleware is what stamps
it in production); ``test_tenant_context_middleware`` covers the stamping.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.accounts.models import Membership, MembershipStatus
from apps.shared import tenancy
from apps.shared.exceptions import TenantContextMissing
from apps.tenants.models import Tenant

UserAccount = get_user_model()


@pytest.fixture(autouse=True)
def _clean():
    yield
    tenancy.clear_request_tenant()
    Membership.objects.all().delete()
    UserAccount.objects.all().delete()
    Tenant.objects.all().delete()


@pytest.fixture
def user(db):
    return UserAccount.objects.create_user(email="member@example.com", password="pw")


def _tenant(code):
    return Tenant.objects.create(code=code, name=code, base_currency="NGN")


def _grant(user, tenant):
    return Membership.objects.create(
        user_account=user, tenant_id=tenant.pk, status=MembershipStatus.ACTIVE
    )


class TestNoContext:
    @pytest.mark.django_db
    def test_without_context_the_queryset_is_unfiltered(self, user):
        t_a = _tenant("acme")
        t_b = _tenant("globex")
        _grant(user, t_a)
        _grant(user, t_b)

        assert Membership.objects.count() == 2

    @pytest.mark.django_db
    def test_require_current_tenant_raises_without_context(self):
        with pytest.raises(TenantContextMissing):
            tenancy.require_current_tenant()


class TestWithContext:
    @pytest.mark.django_db
    def test_auto_filter_returns_only_the_context_tenant(self, user):
        t_a = _tenant("acme")
        t_b = _tenant("globex")
        _grant(user, t_a)
        _grant(user, t_b)

        tenancy.set_request_tenant(t_a.pk)
        assert set(Membership.objects.values_list("tenant_id", flat=True)) == {t_a.pk}

    @pytest.mark.django_db
    def test_other_tenants_rows_are_invisible(self, user):
        t_a = _tenant("acme")
        t_b = _tenant("globex")
        _grant(user, t_a)
        _grant(user, t_b)

        tenancy.set_request_tenant(t_a.pk)
        assert Membership.objects.filter(tenant_id=t_b.pk).count() == 0

    @pytest.mark.django_db
    def test_require_current_tenant_returns_the_context_value(self):
        tenancy.set_request_tenant(42)
        assert tenancy.require_current_tenant() == 42

    @pytest.mark.django_db
    def test_clearing_the_context_restores_unfiltered_queries(self, user):
        t_a = _tenant("acme")
        t_b = _tenant("globex")
        _grant(user, t_a)
        _grant(user, t_b)

        tenancy.set_request_tenant(t_a.pk)
        assert Membership.objects.count() == 1
        tenancy.clear_request_tenant()
        assert Membership.objects.count() == 2


class TestExplicitBypass:
    @pytest.mark.django_db
    def test_unscoped_is_the_deliberate_cross_tenant_act(self, user):
        t_a = _tenant("acme")
        t_b = _tenant("globex")
        _grant(user, t_a)
        _grant(user, t_b)

        tenancy.set_request_tenant(t_a.pk)
        assert Membership.objects.unscoped().count() == 2

    @pytest.mark.django_db
    def test_manager_for_tenant_scopes_explicitly(self, user):
        t_a = _tenant("acme")
        t_b = _tenant("globex")
        _grant(user, t_a)
        _grant(user, t_b)

        tenancy.set_request_tenant(t_a.pk)
        # Explicit for_tenant is not silently ANDed with the context tenant.
        rows = Membership.objects.for_tenant(t_b.pk)
        assert set(rows.values_list("tenant_id", flat=True)) == {t_b.pk}


class TestConcurrencyUnderContext:
    @pytest.mark.django_db
    def test_auto_filter_does_not_mask_the_active_grant_invariant(self, user):
        # The partial unique index still applies inside the scoped manager.
        t_a = _tenant("acme")
        _grant(user, t_a)

        tenancy.set_request_tenant(t_a.pk)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(
                    user_account=user, tenant_id=t_a.pk, status=MembershipStatus.ACTIVE
                )
