"""API tests for the tenant list endpoint (M2.3).

This is the cross-tenant read — the one endpoint that deliberately works
WITHOUT a tenant context, showing the user "what tenants do I belong to?"
"""

import pytest

from tests.api.helpers import login as _login


class TestTenantList:
    @pytest.mark.django_db
    def test_returns_the_users_tenants(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.get("/api/tenants/")

        assert resp.status_code == 200
        codes = [t["code"] for t in resp.data]
        assert "acme" in codes

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, provisioned):
        assert api.get("/api/tenants/").status_code == 403

    @pytest.mark.django_db
    def test_includes_role_names(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.get("/api/tenants/")
        acme = [t for t in resp.data if t["code"] == "acme"][0]

        assert "tenant_owner" in acme["role_names"]
