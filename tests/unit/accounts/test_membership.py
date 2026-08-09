"""Unit tests for Membership — the user↔tenant grant (M2.1, DMS §1).

Order: creation → the partial-unique invariant (at most one ACTIVE grant per
user+tenant, DMS #6) → query helpers → constraints. The grant lifecycle is
driven by the invitation flow in M2.2; M2.1 only models it and validates
against it.
"""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.accounts.models import Membership, MembershipStatus
from apps.tenants.models import Tenant

UserAccount = get_user_model()


@pytest.fixture(autouse=True)
def _clean():
    yield
    Membership.objects.all().delete()
    UserAccount.objects.all().delete()
    Tenant.objects.all().delete()


@pytest.fixture
def tenant_a(db):
    return Tenant.objects.create(code="acme", name="Acme", base_currency="NGN")


@pytest.fixture
def tenant_b(db):
    return Tenant.objects.create(code="globex", name="Globex", base_currency="NGN")


@pytest.fixture
def user(db):
    return UserAccount.objects.create_user(email="owner@example.com", password="pw")


class TestCreation:
    @pytest.mark.django_db
    def test_grant_requires_a_user_and_tenant(self, tenant_a, user):
        grant = Membership.objects.create(user_account=user, tenant_id=tenant_a.pk)

        assert grant.user_account_id == user.pk
        assert grant.tenant_id == tenant_a.pk
        assert grant.status == MembershipStatus.PENDING

    @pytest.mark.django_db
    def test_grant_without_tenant_is_blocked(self, user):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(user_account=user)


class TestActiveGrantInvariant:
    @pytest.mark.django_db
    def test_only_one_active_grant_per_user_and_tenant(self, tenant_a, user):
        # DMS #6: the partial unique index admits one ACTIVE row per pair.
        Membership.objects.create(
            user_account=user, tenant_id=tenant_a.pk, status=MembershipStatus.ACTIVE
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Membership.objects.create(
                    user_account=user, tenant_id=tenant_a.pk, status=MembershipStatus.ACTIVE
                )

    @pytest.mark.django_db
    def test_pending_does_not_block_an_active_grant(self, tenant_a, user):
        Membership.objects.create(user_account=user, tenant_id=tenant_a.pk)
        # The index only constrains ACTIVE rows.
        grant = Membership.objects.create(
            user_account=user, tenant_id=tenant_a.pk, status=MembershipStatus.ACTIVE
        )
        assert grant.pk

    @pytest.mark.django_db
    def test_revoked_makes_room_for_a_fresh_active_grant(self, tenant_a, user):
        first = Membership.objects.create(
            user_account=user, tenant_id=tenant_a.pk, status=MembershipStatus.ACTIVE
        )
        first.status = MembershipStatus.REVOKED
        first.save()

        second = Membership.objects.create(
            user_account=user, tenant_id=tenant_a.pk, status=MembershipStatus.ACTIVE
        )
        assert second.status == MembershipStatus.ACTIVE


class TestQueryHelpers:
    @pytest.mark.django_db
    def test_for_user_returns_a_users_grants(self, tenant_a, tenant_b, user):
        Membership.objects.create(
            user_account=user, tenant_id=tenant_a.pk, status=MembershipStatus.ACTIVE
        )
        Membership.objects.create(
            user_account=user, tenant_id=tenant_b.pk, status=MembershipStatus.ACTIVE
        )

        grants = Membership.objects.for_user(user)
        assert grants.count() == 2

    @pytest.mark.django_db
    def test_active_filters_the_grant_state(self, tenant_a, user):
        Membership.objects.create(user_account=user, tenant_id=tenant_a.pk)  # pending
        Membership.objects.create(
            user_account=user, tenant_id=tenant_a.pk, status=MembershipStatus.ACTIVE
        )

        assert Membership.objects.for_user(user).active().count() == 1


class TestConstraints:
    @pytest.mark.django_db
    def test_invalid_status_is_blocked_at_the_database(self, tenant_a, user):
        grant = Membership.objects.create(user_account=user, tenant_id=tenant_a.pk)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Membership.objects.filter(pk=grant.pk).update(status="half-open")
