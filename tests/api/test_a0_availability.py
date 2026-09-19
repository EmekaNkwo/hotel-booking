"""API tests for the Availability search surface (A0).

Composes ``AvailabilityQuery`` (M7) + ``PricingService.price()`` (M6) —
verified here by checking both halves of the response, and that a missing
rate plan degrades to ``price: null`` rather than a 500.
"""

import datetime as dt

import pytest

from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


def _params(a0_world, **overrides):
    today = a0_world["today"]
    params = {
        "property_id": a0_world["property"].pk,
        "room_type_id": a0_world["room_type"].pk,
        "start": today.isoformat(),
        "end": (today + dt.timedelta(days=2)).isoformat(),
    }
    params.update(overrides)
    return params


class TestAvailabilitySearch:
    @pytest.mark.django_db
    def test_happy_path_returns_remaining_and_price(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/availability/", _params(a0_world), HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert resp.data["sellable"] is True
        assert resp.data["price"]["total_minor_units"] == 20000
        assert resp.data["price_error"] is None

    @pytest.mark.django_db
    def test_missing_rate_plan_degrades_to_null_price_not_500(self, api, a0_world):
        from apps.rooms.models import RoomType

        tenant = a0_world["tenant"]
        unpriced_rt = RoomType.objects.create(
            tenant=tenant,
            code="SUITE",
            name="Suite",
            status=RoomType.Status.ACTIVE,
            max_occupancy=4,
        )
        from apps.availability.services import AvailabilityService

        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=a0_world["property"].id,
            room_type_id=unpriced_rt.id,
            total_units=2,
            start_date=a0_world["today"],
            horizon_days=5,
        )
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(
            "/api/availability/",
            _params(a0_world, room_type_id=unpriced_rt.pk),
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 200
        assert resp.data["price"] is None
        assert resp.data["price_error"]

    @pytest.mark.django_db
    def test_invalid_date_range_is_400(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(
            "/api/availability/",
            _params(
                a0_world,
                start=(a0_world["today"] + dt.timedelta(days=5)).isoformat(),
                end=a0_world["today"].isoformat(),
            ),
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_unknown_property_is_404(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get(
            "/api/availability/",
            _params(a0_world, property_id=999999),
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.get(
            "/api/availability/", _params(a0_world), HTTP_X_TENANT_ID=str(a0_world["tenant"].pk)
        )
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/availability/", _params(a0_world))
        assert resp.status_code == 403
