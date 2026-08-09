"""Unit tests for TenantContextMiddleware (M2.1, SDD §13.2 layer 1).

The middleware resolves the principal once per request and stamps the tenant
context (thread-local + request.tenant_id; set_config is Postgres-only and
exercised by the integration tier). These tests prove the PRINCIPAL-DERIVED
rule (DR-01): the effective tenant always comes from the authenticated user's
active memberships — a client header is honored only after validation, never
trusted.

The echo view lives in tests.urls; middleware tests override ROOT_URLCONF so
prod routing is untouched.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.accounts.models import Membership, MembershipStatus
from apps.shared import tenancy
from apps.tenants.models import Tenant

UserAccount = get_user_model()
ECHO = override_settings(ROOT_URLCONF="tests.urls")


@pytest.fixture(autouse=True)
def _clean():
    yield
    Membership.objects.all().delete()
    UserAccount.objects.all().delete()
    Tenant.objects.all().delete()
    tenancy.clear_request_tenant()


def _tenant(code):
    return Tenant.objects.create(code=code, name=code, base_currency="NGN")


def _grant(user, tenant, status=MembershipStatus.ACTIVE):
    return Membership.objects.create(user_account=user, tenant_id=tenant.pk, status=status)


def _echo(client):
    return client.get("/echo/").json()


class TestAnonymous:
    @ECHO
    @pytest.mark.django_db
    def test_anonymous_request_has_no_tenant_context(self):
        body = _echo(Client())

        assert body["user"] is None
        assert body["request_tenant_id"] is None
        assert body["thread_tenant_id"] is None


class TestSingleMembership:
    @ECHO
    @pytest.mark.django_db
    def test_authenticated_user_auto_selects_the_only_active_membership(self):
        tenant = _tenant("acme")
        user = UserAccount.objects.create_user(email="owner@example.com", password="pw")
        _grant(user, tenant)

        client = Client()
        client.force_login(user)
        body = _echo(client)

        assert body["user"] == "owner@example.com"
        assert body["request_tenant_id"] == tenant.pk
        assert body["thread_tenant_id"] == tenant.pk

    @ECHO
    @pytest.mark.django_db
    def test_a_non_active_membership_does_not_auto_select(self):
        tenant = _tenant("acme")
        user = UserAccount.objects.create_user(email="pending@example.com", password="pw")
        _grant(user, tenant, status=MembershipStatus.PENDING)

        client = Client()
        client.force_login(user)

        assert _echo(client)["request_tenant_id"] is None


class TestHeaderSelection:
    @ECHO
    @pytest.mark.django_db
    def test_validated_header_selects_among_multiple_memberships(self):
        tenant_a = _tenant("acme")
        tenant_b = _tenant("globex")
        user = UserAccount.objects.create_user(email="multi@example.com", password="pw")
        _grant(user, tenant_a)
        _grant(user, tenant_b)

        client = Client()
        client.force_login(user)

        assert _echo(client)["request_tenant_id"] is None  # no selection
        body = client.get("/echo/", headers={"X-Tenant-Id": str(tenant_b.pk)}).json()
        assert body["request_tenant_id"] == tenant_b.pk

    @ECHO
    @pytest.mark.django_db
    def test_header_for_a_tenant_you_do_not_belong_to_is_rejected(self):
        tenant_a = _tenant("acme")
        tenant_b = _tenant("globex")
        user = UserAccount.objects.create_user(email="owner@example.com", password="pw")
        _grant(user, tenant_a)

        client = Client()
        client.force_login(user)

        response = client.get("/echo/", headers={"X-Tenant-Id": str(tenant_b.pk)})
        assert response.status_code == 403

    @ECHO
    @pytest.mark.django_db
    def test_non_integer_header_is_rejected(self):
        tenant = _tenant("acme")
        user = UserAccount.objects.create_user(email="owner@example.com", password="pw")
        _grant(user, tenant)

        client = Client()
        client.force_login(user)

        response = client.get("/echo/", headers={"X-Tenant-Id": "not-a-number"})
        assert response.status_code == 403


class TestNoLeak:
    @ECHO
    @pytest.mark.django_db
    def test_thread_context_is_cleared_after_the_request(self):
        tenant = _tenant("acme")
        user = UserAccount.objects.create_user(email="owner@example.com", password="pw")
        _grant(user, tenant)

        client = Client()
        client.force_login(user)
        assert _echo(client)["thread_tenant_id"] == tenant.pk

        # The request completed; its thread-local context is gone — it cannot
        # leak into the next request or into unrelated test code.
        assert tenancy.current_tenant_id() is None

    @ECHO
    @pytest.mark.django_db
    def test_two_requests_stamp_independent_contexts(self):
        tenant_a = _tenant("acme")
        tenant_b = _tenant("globex")
        user = UserAccount.objects.create_user(email="multi@example.com", password="pw")
        _grant(user, tenant_a)
        _grant(user, tenant_b)

        client = Client()
        client.force_login(user)

        first = client.get("/echo/", headers={"X-Tenant-Id": str(tenant_a.pk)}).json()
        second = client.get("/echo/", headers={"X-Tenant-Id": str(tenant_b.pk)}).json()

        assert first["request_tenant_id"] == tenant_a.pk
        assert second["request_tenant_id"] == tenant_b.pk
        assert tenancy.current_tenant_id() is None
