"""API tests for the Allocation surface (A0).

``AllocateLineView`` delegates to ``AllocationService.allocate_line()``
(M11), unmodified — the scoring/locking behavior is exercised in M11's own
suite; here we check the HTTP contract only.
"""

import datetime as dt

import pytest

from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD
from tests.api.helpers import login as _login


def _confirmed_booking_line_id(api, a0_world, tenant_header):
    today = a0_world["today"]
    created = api.post(
        "/api/reservations/",
        {
            "property_id": a0_world["property"].pk,
            "guest_email": "guest@example.com",
            "lines": [
                {
                    "room_type_id": a0_world["room_type"].pk,
                    "arrival_date": today.isoformat(),
                    "departure_date": (today + dt.timedelta(days=2)).isoformat(),
                    "adults": 2,
                    "quantity": 1,
                }
            ],
        },
        format="json",
        HTTP_X_TENANT_ID=tenant_header,
    )
    reservation_id = created.data["id"]
    api.post(f"/api/reservations/{reservation_id}/request-payment/", HTTP_X_TENANT_ID=tenant_header)
    booking = api.post(
        "/api/bookings/confirm/",
        {"reservation_id": reservation_id},
        format="json",
        HTTP_X_TENANT_ID=tenant_header,
    )
    return booking.data["lines"][0]["id"]


class TestAllocateLine:
    @pytest.mark.django_db
    def test_happy_path_allocates_the_only_eligible_room(self, api, a0_world):
        tenant, room = a0_world["tenant"], a0_world["room"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _confirmed_booking_line_id(api, a0_world, str(tenant.pk))

        resp = api.post(
            "/api/allocation/allocate/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 201
        assert resp.data["room_id"] == room.pk
        assert resp.data["booking_line_id"] == line_id

    @pytest.mark.django_db
    def test_allocating_twice_is_409(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _confirmed_booking_line_id(api, a0_world, str(tenant.pk))
        api.post(
            "/api/allocation/allocate/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.post(
            "/api/allocation/allocate/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_no_eligible_room_is_409(self, api, a0_world):
        from apps.rooms.models import Room

        tenant, room = a0_world["tenant"], a0_world["room"]
        Room.objects.filter(pk=room.pk).update(
            operational_state=Room.OperationalState.OUT_OF_SERVICE
        )
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _confirmed_booking_line_id(api, a0_world, str(tenant.pk))

        resp = api.post(
            "/api/allocation/allocate/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_unknown_booking_line_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            "/api/allocation/allocate/",
            {"booking_line_id": 999999},
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.post(
            "/api/allocation/allocate/",
            {"booking_line_id": 1},
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 403


class TestAllocationByBookingLine:
    @pytest.mark.django_db
    def test_happy_path(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _confirmed_booking_line_id(api, a0_world, str(tenant.pk))
        api.post(
            "/api/allocation/allocate/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.get(
            f"/api/allocation/by-booking-line/{line_id}/", HTTP_X_TENANT_ID=str(tenant.pk)
        )

        assert resp.status_code == 200
        assert resp.data["booking_line_id"] == line_id

    @pytest.mark.django_db
    def test_not_yet_allocated_is_404(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _confirmed_booking_line_id(api, a0_world, str(tenant.pk))

        resp = api.get(
            f"/api/allocation/by-booking-line/{line_id}/", HTTP_X_TENANT_ID=str(tenant.pk)
        )

        assert resp.status_code == 404
