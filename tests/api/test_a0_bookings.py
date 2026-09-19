"""API tests for the Bookings surface (A0).

``BookingConfirmView`` delegates to ``BookingService.confirm()`` (M9), which
itself calls ``ReservationService.convert()`` — a reservation must be
Awaiting_Payment before it can be confirmed into a Booking.
"""

import datetime as dt

import pytest

from apps.bookings.models import BookingStatus
from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


def _reserve_and_request_payment(api, a0_world, tenant_header):
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
    return reservation_id


def _beta_reservation_awaiting_payment(a0_world):
    """A second tenant's own sellable property/room-type/rate-plan/policy
    plus a real Reservation already Awaiting_Payment — used by the R0.1
    cross-tenant regression tests below (mirrors
    ``test_a0_reservations.py::test_cross_tenant_reservation_is_404``'s
    inline beta-tenant setup)."""
    import datetime as _dt

    from apps.availability.services import AvailabilityService
    from apps.policies.services import PolicyService
    from apps.pricing.services import PricingService
    from apps.properties.models import Property
    from apps.reservations.services import ReservationLineRequest, ReservationService
    from apps.rooms.models import RoomType
    from apps.shared.value_objects import GuestCount, StayPeriod
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
    beta_rate_plan = PricingService.create_rate_plan(
        tenant=beta,
        property=beta_prop,
        room_type=beta_rt,
        code="STD-RACK",
        base_rate_minor_units=10000,
        currency=beta_prop.currency,
    )
    PricingService.activate_rate_plan(beta_rate_plan)
    beta_policy = PolicyService.create_draft(
        beta, "deposit", {"required": False}, _dt.date(2020, 1, 1)
    )
    PolicyService.publish(beta_policy.id)

    today = a0_world["today"]
    AvailabilityService.initialize_horizon(
        tenant_id=beta.id,
        property_id=beta_prop.id,
        room_type_id=beta_rt.id,
        total_units=5,
        start_date=today,
        horizon_days=5,
    )
    beta_reservation = ReservationService.reserve(
        tenant=beta,
        property=beta_prop,
        lines=[
            ReservationLineRequest(
                room_type_id=beta_rt.id,
                stay_period=StayPeriod(today, today + dt.timedelta(days=1)),
                guest_count=GuestCount(adults=1, children=0),
            )
        ],
        idempotency_key="beta-r0-1-key",
        guest_email="beta-guest@example.com",
    )
    ReservationService.request_payment(beta_reservation.id, tenant_id=beta.id)
    return beta_reservation


class TestBookingConfirm:
    @pytest.mark.django_db
    def test_happy_path_confirms_a_booking(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        reservation_id = _reserve_and_request_payment(api, a0_world, str(tenant.pk))

        resp = api.post(
            "/api/bookings/confirm/",
            {"reservation_id": reservation_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 201
        assert resp.data["aggregate_status"] == BookingStatus.CONFIRMED
        assert resp.data["reservation_id"] == reservation_id
        assert len(resp.data["lines"]) == 1

    @pytest.mark.django_db
    def test_confirming_a_held_reservation_is_409(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
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
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.post(
            "/api/bookings/confirm/",
            {"reservation_id": created.data["id"]},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.post(
            "/api/bookings/confirm/",
            {"reservation_id": 1},
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_confirming_another_tenants_reservation_is_404_and_does_not_convert_it(
        self, api, a0_world
    ):
        """R0.1 (P0 regression): a Tenant-A caller supplying a Tenant-B
        reservation_id must be rejected exactly like an unknown id — never
        allowed to convert Tenant B's reservation, consume Tenant B's
        inventory, or receive any Tenant B data in the response."""
        from apps.bookings.models import Booking
        from apps.reservations.models import Reservation, ReservationStatus

        tenant = a0_world["tenant"]
        beta_reservation = _beta_reservation_awaiting_payment(a0_world)

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            "/api/bookings/confirm/",
            {"reservation_id": beta_reservation.pk},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 404
        # Exactly the same body as a genuinely unknown reservation_id — the
        # caller cannot distinguish "not yours" from "doesn't exist".
        assert resp.data == {"detail": "reservation not found."}

        # The attack must have had NO side effect on Tenant B's data.
        beta_reservation.refresh_from_db()
        assert beta_reservation.status == ReservationStatus.AWAITING_PAYMENT
        assert not Booking.objects.filter(reservation_id=beta_reservation.pk).exists()
        # And Tenant A's own booking list stays empty — nothing leaked in.
        assert not Booking.objects.filter(tenant_id=tenant.pk).exists()
        unchanged = Reservation.objects.get(pk=beta_reservation.pk)
        assert unchanged.tenant_id == beta_reservation.tenant_id

    @pytest.mark.django_db
    def test_request_payment_on_another_tenants_reservation_is_404(self, api, a0_world):
        """R0.1: the same cross-tenant guard on the earlier request-payment
        step — a Tenant-A caller cannot even move Tenant B's Held
        reservation to Awaiting_Payment."""
        from apps.availability.services import AvailabilityService
        from apps.policies.services import PolicyService
        from apps.pricing.services import PricingService
        from apps.properties.models import Property
        from apps.reservations.models import ReservationStatus
        from apps.reservations.services import ReservationLineRequest, ReservationService
        from apps.rooms.models import RoomType
        from apps.shared.value_objects import GuestCount, StayPeriod
        from apps.tenants.models import Tenant
        from apps.tenants.services import TenantService

        tenant = a0_world["tenant"]
        today = a0_world["today"]

        TenantService.provision(
            code="beta2", name="Beta2", base_currency="NGN", owner_email="beta2-owner@x.example"
        )
        beta = Tenant.objects.get(code="beta2")
        beta_prop = Property.objects.create(
            tenant=beta,
            code="BETA2-T1",
            name="Beta2 Hotel",
            status=Property.Status.ACTIVE,
            currency="NGN",
            timezone="UTC",
            check_in_time="14:00",
            check_out_time="12:00",
        )
        beta_rt = RoomType.objects.create(
            tenant=beta, code="STD", name="Standard", status=RoomType.Status.ACTIVE, max_occupancy=2
        )
        beta_rate_plan = PricingService.create_rate_plan(
            tenant=beta,
            property=beta_prop,
            room_type=beta_rt,
            code="STD-RACK",
            base_rate_minor_units=10000,
            currency=beta_prop.currency,
        )
        PricingService.activate_rate_plan(beta_rate_plan)
        beta_policy = PolicyService.create_draft(
            beta, "deposit", {"required": False}, dt.date(2020, 1, 1)
        )
        PolicyService.publish(beta_policy.id)
        AvailabilityService.initialize_horizon(
            tenant_id=beta.id,
            property_id=beta_prop.id,
            room_type_id=beta_rt.id,
            total_units=5,
            start_date=today,
            horizon_days=5,
        )
        beta_reservation = ReservationService.reserve(
            tenant=beta,
            property=beta_prop,
            lines=[
                ReservationLineRequest(
                    room_type_id=beta_rt.id,
                    stay_period=StayPeriod(today, today + dt.timedelta(days=1)),
                    guest_count=GuestCount(adults=1, children=0),
                )
            ],
            idempotency_key="beta2-r0-1-key",
            guest_email="beta2-guest@example.com",
        )

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            f"/api/reservations/{beta_reservation.pk}/request-payment/",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 404
        beta_reservation.refresh_from_db()
        assert beta_reservation.status == ReservationStatus.HELD


class TestBookingListAndDetail:
    @pytest.mark.django_db
    def test_list_filters_by_status(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        reservation_id = _reserve_and_request_payment(api, a0_world, str(tenant.pk))
        api.post(
            "/api/bookings/confirm/",
            {"reservation_id": reservation_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.get(
            "/api/bookings/",
            {"status": BookingStatus.CONFIRMED},
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1

    @pytest.mark.django_db
    def test_list_filters_by_arrival_date(self, api, a0_world):
        """R1.2: the Dashboard's "arrivals today" widget needs an authoritative
        filtered count rather than scanning a page-1 preview — this is the
        minimal ``?arrival_date=`` filter added for that (apps/bookings/api/
        views.py's ``BookingListView.get()``), against the aggregate's own
        indexed ``arrival_date`` field."""
        tenant = a0_world["tenant"]
        today = a0_world["today"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        reservation_id = _reserve_and_request_payment(api, a0_world, str(tenant.pk))
        api.post(
            "/api/bookings/confirm/",
            {"reservation_id": reservation_id},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        matching = api.get(
            "/api/bookings/",
            {"arrival_date": today.isoformat()},
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        assert matching.status_code == 200
        assert matching.data["count"] == 1

        non_matching = api.get(
            "/api/bookings/",
            {"arrival_date": (today + dt.timedelta(days=30)).isoformat()},
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        assert non_matching.status_code == 200
        assert non_matching.data["count"] == 0

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        assert api.get("/api/bookings/").status_code == 403

    @pytest.mark.django_db
    def test_detail_unknown_booking_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/bookings/999999/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 404
