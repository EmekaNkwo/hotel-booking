"""R0.8 regression: list endpoints must actually paginate, not just have
``DEFAULT_PAGINATION_CLASS``/``PAGE_SIZE`` configured and ignored.

Exhaustively proves the pagination MECHANICS (count/next/previous/page
size) once, against Rooms (the cheapest model to create in bulk — no
reservation/availability chain needed). Every other prioritized list
endpoint (reservations, bookings, guests, housekeeping, notifications) gets
one crisp shape-confirmation test — the mechanism is shared
(``apps.shared.api.pagination.paginate_list``), so re-proving the full
boundary matrix on each would be redundant, not more protective.
"""

import pytest
from django.conf import settings

from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD
from tests.api.helpers import login as _login


@pytest.mark.django_db
class TestRoomPaginationMechanics:
    def test_page_size_matches_settings_and_more_pages_are_signaled(self, api, a0_world):
        from apps.rooms.models import Room

        tenant = a0_world["tenant"]
        property_ = a0_world["property"]
        room_type = a0_world["room_type"]
        page_size = settings.REST_FRAMEWORK["PAGE_SIZE"]
        # a0_world already created one room ("101") — top up to page_size + 3.
        existing = Room.objects.filter(tenant=tenant).count()
        for i in range(existing, page_size + 3):
            Room.objects.create(
                tenant=tenant,
                property=property_,
                room_type=room_type,
                code=f"P{i}",
                operational_state=Room.OperationalState.VACANT_CLEAN,
            )
        total = Room.objects.filter(tenant=tenant).count()
        assert total == page_size + 3

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        first = api.get("/api/rooms/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert first.status_code == 200
        assert set(first.data.keys()) == {"count", "next", "previous", "results"}
        assert first.data["count"] == total
        assert len(first.data["results"]) == page_size
        assert first.data["previous"] is None
        assert first.data["next"] is not None

    def test_second_page_returns_the_remainder_and_no_next(self, api, a0_world):
        from apps.rooms.models import Room

        tenant = a0_world["tenant"]
        property_ = a0_world["property"]
        room_type = a0_world["room_type"]
        page_size = settings.REST_FRAMEWORK["PAGE_SIZE"]
        existing = Room.objects.filter(tenant=tenant).count()
        for i in range(existing, page_size + 3):
            Room.objects.create(
                tenant=tenant,
                property=property_,
                room_type=room_type,
                code=f"Q{i}",
                operational_state=Room.OperationalState.VACANT_CLEAN,
            )
        total = Room.objects.filter(tenant=tenant).count()

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        second = api.get("/api/rooms/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))

        assert second.status_code == 200
        assert len(second.data["results"]) == total - page_size
        assert second.data["previous"] is not None
        assert second.data["next"] is None

    def test_a_single_short_page_has_no_next_or_previous(self, api, a0_world):
        """Baseline: well under PAGE_SIZE, still returns the paginated
        envelope, just with both links null (already exercised implicitly
        by every other A0 list test that asserts on `.data["results"]`;
        this makes the envelope shape itself an explicit assertion)."""
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.get("/api/rooms/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert resp.data["next"] is None
        assert resp.data["previous"] is None
        assert resp.data["count"] == len(resp.data["results"])


@pytest.mark.django_db
class TestPaginationAppliesAcrossPrioritizedListEndpoints:
    """Shape-only confirmation that every R0.8-prioritized list endpoint
    returns the same paginated envelope, not a bare array."""

    def test_reservations_list_is_paginated(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/reservations/", HTTP_X_TENANT_ID=str(tenant.pk))
        assert resp.status_code == 200
        assert set(resp.data.keys()) == {"count", "next", "previous", "results"}

    def test_bookings_list_is_paginated(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/bookings/", HTTP_X_TENANT_ID=str(tenant.pk))
        assert resp.status_code == 200
        assert set(resp.data.keys()) == {"count", "next", "previous", "results"}

    def test_guests_list_is_paginated(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/guests/", {"q": "x"}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert resp.status_code == 200
        assert set(resp.data.keys()) == {"count", "next", "previous", "results"}

    def test_housekeeping_tasks_list_is_paginated(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/housekeeping/tasks/", HTTP_X_TENANT_ID=str(tenant.pk))
        assert resp.status_code == 200
        assert set(resp.data.keys()) == {"count", "next", "previous", "results"}

    def test_notifications_list_is_paginated(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/notifications/", HTTP_X_TENANT_ID=str(tenant.pk))
        assert resp.status_code == 200
        assert set(resp.data.keys()) == {"count", "next", "previous", "results"}
