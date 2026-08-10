"""API tests for the role endpoints — list and create (M2.3).

The RBAC matrix at the API boundary: list requires ``role.view``, create
requires ``role.manage``, and a user who has neither (or a weaker role) is
denied at the permission class — before any service logic runs.
"""

import pytest

from tests.api.helpers import login as _login


class TestRoleList:
    @pytest.mark.django_db
    def test_owner_can_list_roles(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.get("/api/roles/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 200
        names = {r["name"] for r in resp.data}
        assert "tenant_owner" in names
        assert "front_desk" in names

    @pytest.mark.django_db
    def test_viewer_without_role_view_gets_403(self, api, provisioned):
        _login(api, "viewer@acme.example", "Viewer!pw123!")

        resp = api.get("/api/roles/", HTTP_X_TENANT_ID="1")

        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_unauthenticated_gets_403(self, api, provisioned):
        assert api.get("/api/roles/", HTTP_X_TENANT_ID="1").status_code == 403


class TestRoleCreate:
    @pytest.mark.django_db
    def test_owner_can_create_a_role_with_permissions(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post(
            "/api/roles/create/",
            {"name": "housekeeping", "permission_codes": ["member.view"]},
            format="json",
            HTTP_X_TENANT_ID="1",
        )

        assert resp.status_code == 201
        assert resp.data["name"] == "housekeeping"
        assert resp.data["permission_codes"] == ["member.view"]
        assert resp.data["status"] == "draft"

    @pytest.mark.django_db
    def test_invalid_permission_code_is_rejected(self, api, provisioned):
        _login(api, "owner@acme.example", "Owner!pw123!")

        resp = api.post(
            "/api/roles/create/",
            {"name": "rogue", "permission_codes": ["member.invite_everyone"]},
            format="json",
            HTTP_X_TENANT_ID="1",
        )

        assert resp.status_code == 400
        assert "unknown permission code" in resp.data["detail"]

    @pytest.mark.django_db
    def test_viewer_without_role_manage_gets_403(self, api, provisioned):
        _login(api, "viewer@acme.example", "Viewer!pw123!")

        resp = api.post(
            "/api/roles/create/",
            {"name": "housekeeping", "permission_codes": ["member.view"]},
            format="json",
            HTTP_X_TENANT_ID="1",
        )

        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_unauthenticated_gets_403(self, api, provisioned):
        resp = api.post("/api/roles/create/", {}, format="json", HTTP_X_TENANT_ID="1")
        assert resp.status_code == 403
