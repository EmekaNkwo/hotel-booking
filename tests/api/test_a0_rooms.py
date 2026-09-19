"""API tests for the Rooms surface (A0).

``Room``/``RoomType`` use ``TenantScopedManager`` (M3) — isolation is
enforced by the manager reading the request's tenant context, not by an
explicit ``tenant_id=`` filter in the view.
"""

import pytest

from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


class TestRoomList:
    @pytest.mark.django_db
    def test_happy_path_lists_rooms(self, api, a0_world):
        tenant, room = a0_world["tenant"], a0_world["room"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/rooms/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        codes = [r["code"] for r in resp.data["results"]]
        assert room.code in codes
        assert resp.data["results"][0]["room_type"]["code"] == a0_world["room_type"].code

    @pytest.mark.django_db
    def test_filters_by_operational_state(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(
            "/api/rooms/",
            {"operational_state": "out_of_service"},
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 200
        assert resp.data["results"] == []

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.get("/api/rooms/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/rooms/")
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_cross_tenant_room_is_invisible(self, api, a0_world):
        """A room in another tenant never appears — TenantScopedManager isolation."""
        from apps.properties.models import Property
        from apps.rooms.models import Room, RoomType
        from apps.tenants.models import Tenant
        from apps.tenants.services import TenantService

        TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta-owner@x.example"
        )
        beta = Tenant.objects.get(code="beta")
        beta_prop = Property.objects.create(
            tenant=beta,
            code="BETA-T1",
            name="Beta Hotel",
            status=Property.Status.ACTIVE,
            currency="NGN",
            timezone="UTC",
            check_in_time="14:00",
            check_out_time="12:00",
        )
        beta_rt = RoomType.objects.create(
            tenant=beta, code="STD", name="Standard", status=RoomType.Status.ACTIVE, max_occupancy=2
        )
        Room.objects.create(
            tenant=beta,
            property=beta_prop,
            room_type=beta_rt,
            code="BETA-101",
            operational_state=Room.OperationalState.VACANT_CLEAN,
        )

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/rooms/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))

        assert resp.status_code == 200
        codes = [r["code"] for r in resp.data["results"]]
        assert "BETA-101" not in codes


class TestRoomDetail:
    @pytest.mark.django_db
    def test_happy_path(self, api, a0_world):
        tenant, room = a0_world["tenant"], a0_world["room"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(f"/api/rooms/{room.pk}/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert resp.data["code"] == room.code

    @pytest.mark.django_db
    def test_unknown_room_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/rooms/999999/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 404


class TestRoomTypeList:
    @pytest.mark.django_db
    def test_only_active_room_types_are_listed(self, api, a0_world):
        from apps.rooms.models import RoomType

        tenant, room_type = a0_world["tenant"], a0_world["room_type"]
        RoomType.objects.create(
            tenant=tenant,
            code="RETIRED",
            name="Old wing",
            status=RoomType.Status.RETIRED,
            max_occupancy=2,
        )
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/room-types/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        codes = [rt["code"] for rt in resp.data]
        assert room_type.code in codes
        assert "RETIRED" not in codes
