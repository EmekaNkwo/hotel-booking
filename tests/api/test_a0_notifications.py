"""API tests for the Notifications surface (A0).

Read-only — M13 exposes no staff-triggerable mutation (delivery is
Celery/projector-driven). These tests create jobs directly against the
``NotificationJob`` model (a plain manager, M13) to exercise the HTTP read
contract without depending on Celery/the projector being wired up.
"""

import pytest

from apps.notifications.models import JobStatus
from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


def _make_job(tenant, status=JobStatus.PENDING, **overrides):
    from apps.notifications.models import NotificationJob

    defaults = dict(
        tenant_id=tenant.pk,
        notification_type="reservation.created",
        channel="email",
        status=status,
        context={"reservation_ref": "ABC123"},
    )
    defaults.update(overrides)
    return NotificationJob.objects.create(**defaults)


class TestNotificationList:
    @pytest.mark.django_db
    def test_happy_path_lists_jobs(self, api, a0_world):
        tenant = a0_world["tenant"]
        _make_job(tenant)
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/notifications/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["notification_type"] == "reservation.created"

    @pytest.mark.django_db
    def test_filters_by_status(self, api, a0_world):
        tenant = a0_world["tenant"]
        _make_job(tenant, status=JobStatus.DELIVERED)
        _make_job(tenant, status=JobStatus.PENDING)
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(
            "/api/notifications/", {"status": JobStatus.DELIVERED}, HTTP_X_TENANT_ID=str(tenant.pk)
        )

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["status"] == JobStatus.DELIVERED

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.get("/api/notifications/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        assert api.get("/api/notifications/").status_code == 403

    @pytest.mark.django_db
    def test_cross_tenant_job_is_invisible(self, api, a0_world):
        from apps.tenants.models import Tenant
        from apps.tenants.services import TenantService

        TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta-owner@x.example"
        )
        beta = Tenant.objects.get(code="beta")
        _make_job(beta)
        _make_job(a0_world["tenant"])

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/notifications/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1


class TestNotificationDetail:
    @pytest.mark.django_db
    def test_happy_path(self, api, a0_world):
        tenant = a0_world["tenant"]
        job = _make_job(tenant)
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(f"/api/notifications/{job.pk}/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert resp.data["id"] == job.pk

    @pytest.mark.django_db
    def test_unknown_job_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/notifications/999999/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_cross_tenant_job_detail_is_404(self, api, a0_world):
        from apps.tenants.models import Tenant
        from apps.tenants.services import TenantService

        TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta-owner@x.example"
        )
        beta = Tenant.objects.get(code="beta")
        job = _make_job(beta)

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get(f"/api/notifications/{job.pk}/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))

        assert resp.status_code == 404
