"""API tests for the Properties surface (A2 addition to A0's thin HTTP layer).

Added because availability search (`GET /api/availability/`) requires a
`property_id` the UI has no other way to discover — see
`apps/properties/api/serializers.py`'s module docstring.
"""

import pytest

from apps.properties.models import Property
from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


class TestPropertyList:
    @pytest.mark.django_db
    def test_happy_path_lists_active_properties(self, api, a0_world):
        tenant, property_ = a0_world["tenant"], a0_world["property"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/properties/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        codes = [p["code"] for p in resp.data]
        assert property_.code in codes

    @pytest.mark.django_db
    def test_draft_properties_are_excluded(self, api, a0_world):
        tenant = a0_world["tenant"]
        Property.objects.create(
            tenant=tenant,
            code="DRAFT1",
            name="Draft Hotel",
            status=Property.Status.DRAFT,
            currency="NGN",
            timezone="UTC",
            check_in_time="14:00",
            check_out_time="12:00",
        )
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/properties/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        codes = [p["code"] for p in resp.data]
        assert "DRAFT1" not in codes

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.get("/api/properties/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        assert api.get("/api/properties/").status_code == 403

    @pytest.mark.django_db
    def test_cross_tenant_property_is_invisible(self, api, a0_world):
        from apps.tenants.models import Tenant
        from apps.tenants.services import TenantService

        TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta-owner@x.example"
        )
        beta = Tenant.objects.get(code="beta")
        Property.objects.create(
            tenant=beta,
            code="BETA-T1",
            name="Beta Hotel",
            status=Property.Status.ACTIVE,
            currency="NGN",
            timezone="UTC",
            check_in_time="14:00",
            check_out_time="12:00",
        )

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/properties/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))

        assert resp.status_code == 200
        codes = [p["code"] for p in resp.data]
        assert "BETA-T1" not in codes


class TestPropertyDetail:
    @pytest.mark.django_db
    def test_happy_path(self, api, a0_world):
        tenant, property_ = a0_world["tenant"], a0_world["property"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(f"/api/properties/{property_.pk}/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert resp.data["code"] == property_.code

    @pytest.mark.django_db
    def test_unknown_property_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/properties/999999/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 404
