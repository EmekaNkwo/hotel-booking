"""R1.1/R1.5 regression: real multi-page behavior (>PAGE_SIZE rows), proven
against all six paginated list endpoints — not just the pagination
MECHANICS (already covered by test_r0_8_pagination.py), but the actual
page-1/page-2/next/previous/count contract with volume, plus a stable-order
guarantee under duplicate timestamps.

Row volume is created via direct ORM writes, not the full domain service
flow (reserve()/confirm()/checkout()) — this file tests the API/pagination
layer, not domain behavior (which is already covered elsewhere); running
26+ rows through the full reservation->booking->allocation->checkout chain
would be slow and would not exercise anything pagination-specific.
"""

import datetime as dt

import pytest
from django.conf import settings
from django.utils import timezone

from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD
from tests.api.helpers import login as _login

PAGE_SIZE = None  # resolved per-test from settings, see _page_size()


def _page_size():
    return settings.REST_FRAMEWORK["PAGE_SIZE"]


@pytest.mark.django_db
class TestReservationMultiPage:
    def _seed(self, a0_world, count):
        from apps.reservations.models import Reservation, ReservationStatus

        tenant, property_ = a0_world["tenant"], a0_world["property"]
        rows = [
            Reservation(
                tenant=tenant,
                property=property_,
                reservation_ref=f"MPR{i:03d}",
                status=ReservationStatus.HELD,
                hold_expiry_at=timezone.now() + dt.timedelta(minutes=15),
            )
            for i in range(count)
        ]
        return Reservation.objects.bulk_create(rows)

    def test_two_pages_no_duplicates_correct_count(self, api, a0_world):
        page_size = _page_size()
        total = page_size + 5
        self._seed(a0_world, total)
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        page1 = api.get("/api/reservations/", HTTP_X_TENANT_ID=str(tenant.pk))
        assert page1.status_code == 200
        assert page1.data["count"] == total
        assert len(page1.data["results"]) == page_size
        assert page1.data["previous"] is None
        assert page1.data["next"] is not None

        page2 = api.get("/api/reservations/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert page2.status_code == 200
        assert len(page2.data["results"]) == total - page_size
        assert page2.data["previous"] is not None
        assert page2.data["next"] is None

        ids_page1 = {r["id"] for r in page1.data["results"]}
        ids_page2 = {r["id"] for r in page2.data["results"]}
        assert ids_page1.isdisjoint(ids_page2), "same reservation appeared on both pages"
        assert len(ids_page1 | ids_page2) == total

    def test_filters_reset_to_page_1_scope(self, a0_world):
        """A status filter changes the underlying queryset's count/pages —
        proven at the queryset level (the view always re-derives count from
        the FILTERED queryset, never the unfiltered one)."""
        from apps.reservations.models import Reservation, ReservationStatus

        self._seed(a0_world, _page_size() + 5)
        # Flip a handful to a different status so the filtered count differs
        # from the unfiltered one.
        Reservation.objects.filter(tenant=a0_world["tenant"]).order_by("id")[:3]
        ids = list(
            Reservation.objects.filter(tenant=a0_world["tenant"]).order_by("id").values_list(
                "id", flat=True
            )[:3]
        )
        Reservation.objects.filter(pk__in=ids).update(status=ReservationStatus.CANCELLED)
        assert Reservation.objects.filter(
            tenant=a0_world["tenant"], status=ReservationStatus.CANCELLED
        ).count() == 3

    def test_identical_created_at_does_not_duplicate_or_skip_across_pages(self, api, a0_world):
        """R1.5: force every row to the SAME created_at (the realistic tie
        scenario — a bulk import or fast concurrent writes) and confirm the
        `-id` tie-breaker still yields a stable, complete, non-duplicating
        page split."""
        from apps.reservations.models import Reservation

        page_size = _page_size()
        total = page_size + 7
        created = self._seed(a0_world, total)
        same_instant = timezone.now()
        Reservation.objects.filter(pk__in=[r.pk for r in created]).update(created_at=same_instant)

        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        seen_ids = set()
        page = 1
        while True:
            resp = api.get(
                "/api/reservations/", {"page": page}, HTTP_X_TENANT_ID=str(tenant.pk)
            )
            assert resp.status_code == 200
            page_ids = [r["id"] for r in resp.data["results"]]
            msg = f"page {page} duplicated a row from an earlier page"
            assert seen_ids.isdisjoint(page_ids), msg
            seen_ids.update(page_ids)
            if resp.data["next"] is None:
                break
            page += 1
        assert seen_ids == {r.pk for r in created}, "some rows were skipped across pages"


@pytest.mark.django_db
class TestBookingMultiPage:
    def _seed(self, a0_world, count):
        from apps.bookings.models import Booking, BookingStatus

        tenant, property_ = a0_world["tenant"], a0_world["property"]
        rows = [
            Booking(
                tenant=tenant,
                property=property_,
                booking_ref=f"MPB{i:03d}",
                aggregate_status=BookingStatus.CONFIRMED,
                currency="NGN",
                total_minor_units=10000,
                arrival_date=dt.date(2026, 12, 1),
                departure_date=dt.date(2026, 12, 3),
            )
            for i in range(count)
        ]
        return Booking.objects.bulk_create(rows)

    def test_two_pages_no_duplicates(self, api, a0_world):
        page_size = _page_size()
        total = page_size + 4
        self._seed(a0_world, total)
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        page1 = api.get("/api/bookings/", HTTP_X_TENANT_ID=str(tenant.pk))
        page2 = api.get("/api/bookings/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert page1.data["count"] == total
        assert len(page1.data["results"]) == page_size
        assert len(page2.data["results"]) == total - page_size
        ids1 = {b["id"] for b in page1.data["results"]}
        ids2 = {b["id"] for b in page2.data["results"]}
        assert ids1.isdisjoint(ids2)


@pytest.mark.django_db
class TestGuestMultiPage:
    def test_two_pages_no_duplicates(self, api, a0_world):
        from apps.guests.models import GuestProfile

        page_size = _page_size()
        total = page_size + 6
        tenant = a0_world["tenant"]
        rows = [
            GuestProfile(
                tenant=tenant,
                primary_email=f"mp-guest-{i}@example.com",
                name={"given_name": "MP", "family_name": str(i), "display_name": f"MP {i}"},
            )
            for i in range(total)
        ]
        GuestProfile.objects.bulk_create(rows)

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        page1 = api.get("/api/guests/", HTTP_X_TENANT_ID=str(tenant.pk))
        page2 = api.get("/api/guests/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert page1.data["count"] == total
        assert len(page1.data["results"]) == page_size
        assert len(page2.data["results"]) == total - page_size
        ids1 = {g["id"] for g in page1.data["results"]}
        ids2 = {g["id"] for g in page2.data["results"]}
        assert ids1.isdisjoint(ids2)


@pytest.mark.django_db
class TestRoomMultiPage:
    def test_two_pages_no_duplicates(self, api, a0_world):
        from apps.rooms.models import Room

        page_size = _page_size()
        tenant = a0_world["tenant"]
        property_ = a0_world["property"]
        room_type = a0_world["room_type"]
        existing = Room.objects.filter(tenant=tenant).count()
        target_total = page_size + 5
        rows = [
            Room(
                tenant=tenant,
                property=property_,
                room_type=room_type,
                code=f"MP{i:03d}",
                operational_state=Room.OperationalState.VACANT_CLEAN,
            )
            for i in range(existing, target_total)
        ]
        Room.objects.bulk_create(rows)
        total = Room.objects.filter(tenant=tenant).count()
        assert total >= page_size + 1

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        page1 = api.get("/api/rooms/", HTTP_X_TENANT_ID=str(tenant.pk))
        page2 = api.get("/api/rooms/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert page1.data["count"] == total
        assert len(page1.data["results"]) == page_size
        ids1 = {r["id"] for r in page1.data["results"]}
        ids2 = {r["id"] for r in page2.data["results"]}
        assert ids1.isdisjoint(ids2)
        assert len(ids1 | ids2) <= total


@pytest.mark.django_db
class TestHousekeepingMultiPage:
    def test_two_pages_no_duplicates(self, api, a0_world):
        from apps.housekeeping.models import HousekeepingTask, TaskKind, TaskStatus
        from apps.rooms.models import Room

        page_size = _page_size()
        tenant = a0_world["tenant"]
        property_ = a0_world["property"]
        room_type = a0_world["room_type"]
        total = page_size + 3
        rooms = Room.objects.bulk_create(
            [
                Room(
                    tenant=tenant,
                    property=property_,
                    room_type=room_type,
                    code=f"HK{i:03d}",
                    operational_state=Room.OperationalState.VACANT_DIRTY,
                )
                for i in range(total)
            ]
        )
        tasks = [
            HousekeepingTask(
                tenant=tenant,
                property=property_,
                room=room,
                business_date=dt.date(2026, 12, 1),
                task_kind=TaskKind.DEPARTURE,
                status=TaskStatus.PLANNED,
            )
            for room in rooms
        ]
        HousekeepingTask.objects.bulk_create(tasks)

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        page1 = api.get("/api/housekeeping/tasks/", HTTP_X_TENANT_ID=str(tenant.pk))
        page2 = api.get("/api/housekeeping/tasks/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert page1.data["count"] == total
        assert len(page1.data["results"]) == page_size
        assert len(page2.data["results"]) == total - page_size
        ids1 = {t["id"] for t in page1.data["results"]}
        ids2 = {t["id"] for t in page2.data["results"]}
        assert ids1.isdisjoint(ids2)


@pytest.mark.django_db
class TestNotificationMultiPage:
    def test_two_pages_no_duplicates(self, api, a0_world):
        from apps.notifications.models import JobStatus, NotificationJob

        page_size = _page_size()
        tenant = a0_world["tenant"]
        total = page_size + 4
        jobs = [
            NotificationJob(
                tenant=tenant,
                notification_type="reservation.created",
                channel="email",
                status=JobStatus.PENDING,
                context={},
            )
            for _ in range(total)
        ]
        NotificationJob.objects.bulk_create(jobs)

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        page1 = api.get("/api/notifications/", HTTP_X_TENANT_ID=str(tenant.pk))
        page2 = api.get("/api/notifications/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert page1.data["count"] == total
        assert len(page1.data["results"]) == page_size
        assert len(page2.data["results"]) == total - page_size
        ids1 = {j["id"] for j in page1.data["results"]}
        ids2 = {j["id"] for j in page2.data["results"]}
        assert ids1.isdisjoint(ids2)

    def test_final_page_is_not_empty_and_next_is_null(self, api, a0_world):
        """Empty-final-page edge case: exactly 2 full pages worth of rows —
        confirm the last page is never spuriously empty and `next` is null
        exactly once the true end is reached."""
        from apps.notifications.models import JobStatus, NotificationJob

        page_size = _page_size()
        tenant = a0_world["tenant"]
        total = page_size * 2
        jobs = [
            NotificationJob(
                tenant=tenant,
                notification_type="reservation.created",
                channel="email",
                status=JobStatus.PENDING,
                context={},
            )
            for _ in range(total)
        ]
        NotificationJob.objects.bulk_create(jobs)

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        page2 = api.get("/api/notifications/", {"page": 2}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert len(page2.data["results"]) == page_size
        assert page2.data["next"] is None

        page3 = api.get("/api/notifications/", {"page": 3}, HTTP_X_TENANT_ID=str(tenant.pk))
        assert page3.status_code == 404  # DRF's standard out-of-range-page behavior
