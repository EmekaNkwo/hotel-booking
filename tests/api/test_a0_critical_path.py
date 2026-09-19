"""A0 critical-path integration test: the full staff HTTP journey through
every M6-M13 milestone, over real HTTP calls only — no faked business
state, no direct service calls to skip a step.

login -> select tenant -> availability search -> create reservation ->
request payment -> confirm booking -> allocate room -> checkout ->
start cleaning -> complete cleaning -> inspect -> notification retrieval.
"""

import datetime as dt

import pytest

from apps.bookings.models import BookingStatus
from apps.housekeeping.models import TaskStatus
from apps.reservations.models import ReservationStatus
from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD
from tests.api.helpers import login as _login


@pytest.mark.django_db
def test_full_critical_path_journey(api, a0_world):
    tenant = a0_world["tenant"]
    today = a0_world["today"]
    tid = str(tenant.pk)

    # 1. Login.
    resp = _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
    assert resp.status_code == 200

    # 2. Select tenant (the cross-tenant membership list).
    resp = api.get("/api/tenants/")
    assert resp.status_code == 200
    assert any(t["code"] == "acme" for t in resp.data)

    # 3. Availability search.
    resp = api.get(
        "/api/availability/",
        {
            "property_id": a0_world["property"].pk,
            "room_type_id": a0_world["room_type"].pk,
            "start": today.isoformat(),
            "end": (today + dt.timedelta(days=2)).isoformat(),
        },
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 200
    assert resp.data["sellable"] is True

    # 4. Create reservation.
    resp = api.post(
        "/api/reservations/",
        {
            "property_id": a0_world["property"].pk,
            "guest_email": "journey-guest@example.com",
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
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 201
    assert resp.data["status"] == ReservationStatus.HELD
    reservation_id = resp.data["id"]

    # 5. Request payment.
    resp = api.post(f"/api/reservations/{reservation_id}/request-payment/", HTTP_X_TENANT_ID=tid)
    assert resp.status_code == 200
    assert resp.data["status"] == ReservationStatus.AWAITING_PAYMENT

    # 6. Confirm booking.
    resp = api.post(
        "/api/bookings/confirm/",
        {"reservation_id": reservation_id},
        format="json",
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 201
    assert resp.data["aggregate_status"] == BookingStatus.CONFIRMED
    booking_line_id = resp.data["lines"][0]["id"]

    # 7. Allocate room.
    resp = api.post(
        "/api/allocation/allocate/",
        {"booking_line_id": booking_line_id},
        format="json",
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 201
    assert resp.data["room_id"] == a0_world["room"].pk

    # 8. Checkout (opens the departure cleaning task).
    resp = api.post(
        "/api/housekeeping/checkout/",
        {"booking_line_id": booking_line_id},
        format="json",
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 201
    assert resp.data["status"] == TaskStatus.PLANNED
    task_id = resp.data["id"]

    # 9. Start cleaning.
    resp = api.post(
        f"/api/housekeeping/tasks/{task_id}/start-cleaning/",
        {},
        format="json",
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 200
    assert resp.data["status"] == TaskStatus.IN_PROGRESS

    # 10. Complete cleaning.
    resp = api.post(
        f"/api/housekeeping/tasks/{task_id}/complete-cleaning/",
        {},
        format="json",
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 200
    assert resp.data["status"] == TaskStatus.QUALITY_CHECK

    # 11. Inspect (pass).
    resp = api.post(
        f"/api/housekeeping/tasks/{task_id}/inspect/",
        {"result": "pass"},
        format="json",
        HTTP_X_TENANT_ID=tid,
    )
    assert resp.status_code == 200
    assert resp.data["status"] == TaskStatus.VERIFIED

    # 12. Notification retrieval (read-only visibility into the outbox
    #     consumer's output — may be empty since the projector/Celery
    #     relay isn't running synchronously in this test, but the endpoint
    #     itself must respond correctly for the tenant).
    resp = api.get("/api/notifications/", HTTP_X_TENANT_ID=tid)
    assert resp.status_code == 200
    assert isinstance(resp.data["results"], list)

    # Final state sanity: the room is back to a sellable state, and the
    # whole chain is queryable end-to-end via GETs.
    from apps.rooms.models import Room

    room = Room.objects.get(pk=a0_world["room"].pk)
    assert room.operational_state == Room.OperationalState.VACANT_CLEAN

    resp = api.get(f"/api/allocation/by-booking-line/{booking_line_id}/", HTTP_X_TENANT_ID=tid)
    assert resp.status_code == 200
    resp = api.get(f"/api/reservations/{reservation_id}/", HTTP_X_TENANT_ID=tid)
    assert resp.status_code == 200
    resp = api.get(f"/api/housekeeping/tasks/{task_id}/", HTTP_X_TENANT_ID=tid)
    assert resp.status_code == 200
