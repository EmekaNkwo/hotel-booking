"""API tests for the Housekeeping surface (A0).

Every mutating view delegates to ``HousekeepingService`` verbatim — the
task/Room FSM pair advances exactly as it does in M12's own suite.
"""

import datetime as dt

import pytest

from apps.housekeeping.models import TaskStatus
from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


def _checked_in_line_id(api, a0_world, tenant_header):
    """Build a confirmed + allocated line — ``AllocationService.allocate_line()``
    (M11) already drives the Room FSM ``vacant_clean -> occupied_clean`` on
    allocation, so the room is ready for checkout with no separate
    check-in step (A0 exposes no check-in endpoint; out of scope)."""
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
    line_id = booking.data["lines"][0]["id"]
    api.post(
        "/api/allocation/allocate/",
        {"booking_line_id": line_id},
        format="json",
        HTTP_X_TENANT_ID=tenant_header,
    )
    return line_id


class TestHousekeepingCheckout:
    @pytest.mark.django_db
    def test_happy_path_creates_a_departure_task(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _checked_in_line_id(api, a0_world, str(tenant.pk))

        resp = api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 201
        assert resp.data["status"] == TaskStatus.PLANNED
        assert resp.data["room_id"] == a0_world["room"].pk

    @pytest.mark.django_db
    def test_double_checkout_is_409(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _checked_in_line_id(api, a0_world, str(tenant.pk))
        api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_unknown_booking_line_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": 999999},
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": 1},
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 403


class TestHousekeepingTaskLifecycle:
    @pytest.mark.django_db
    def test_full_clean_and_inspect_cycle(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _checked_in_line_id(api, a0_world, str(tenant.pk))
        checkout = api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        task_id = checkout.data["id"]

        start = api.post(
            f"/api/housekeeping/tasks/{task_id}/start-cleaning/",
            {},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        assert start.status_code == 200
        assert start.data["status"] == TaskStatus.IN_PROGRESS

        complete = api.post(
            f"/api/housekeeping/tasks/{task_id}/complete-cleaning/",
            {},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        assert complete.status_code == 200
        assert complete.data["status"] == TaskStatus.QUALITY_CHECK

        inspect = api.post(
            f"/api/housekeeping/tasks/{task_id}/inspect/",
            {"result": "pass"},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        assert inspect.status_code == 200
        assert inspect.data["status"] == TaskStatus.VERIFIED

    @pytest.mark.django_db
    def test_starting_a_task_not_yet_planned_stage_is_409(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _checked_in_line_id(api, a0_world, str(tenant.pk))
        checkout = api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        task_id = checkout.data["id"]
        api.post(
            f"/api/housekeeping/tasks/{task_id}/start-cleaning/",
            {},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.post(
            f"/api/housekeeping/tasks/{task_id}/inspect/",
            {"result": "pass"},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_unknown_task_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            "/api/housekeeping/tasks/999999/start-cleaning/",
            {},
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_list_filters_by_status(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        line_id = _checked_in_line_id(api, a0_world, str(tenant.pk))
        api.post(
            "/api/housekeeping/checkout/",
            {"booking_line_id": line_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.get(
            "/api/housekeeping/tasks/",
            {"status": TaskStatus.PLANNED},
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        assert api.get("/api/housekeeping/tasks/").status_code == 403
