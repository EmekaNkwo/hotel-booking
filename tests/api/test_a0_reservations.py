"""API tests for the Reservations surface (A0).

Every mutating view delegates to ``ReservationService`` verbatim — these
tests check the view's own concerns (auth, tenancy, input shape, status
mapping) and cross-check the resulting DB state matches what
``ReservationService`` itself guarantees (M8).
"""

import datetime as dt

import pytest

from apps.reservations.models import Reservation, ReservationStatus
from tests.api.conftest import VIEWER_EMAIL, VIEWER_PASSWORD, grant_second_membership
from tests.api.helpers import login as _login


def _create_payload(a0_world, **overrides):
    today = a0_world["today"]
    payload = {
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
    }
    payload.update(overrides)
    return payload


class TestReservationCreate:
    @pytest.mark.django_db
    def test_happy_path_holds_a_reservation(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 201
        assert resp.data["status"] == ReservationStatus.HELD
        assert len(resp.data["lines"]) == 1
        reservation = Reservation.objects.get(pk=resp.data["id"])
        assert reservation.tenant_id == tenant.pk

    @pytest.mark.django_db
    def test_empty_lines_is_400(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            "/api/reservations/",
            _create_payload(a0_world, lines=[]),
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_insufficient_availability_is_409(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)

        resp = api.post(
            "/api/reservations/",
            _create_payload(
                a0_world,
                lines=[
                    {
                        "room_type_id": a0_world["room_type"].pk,
                        "arrival_date": a0_world["today"].isoformat(),
                        "departure_date": (a0_world["today"] + dt.timedelta(days=2)).isoformat(),
                        "adults": 2,
                        "quantity": 999,
                    }
                ],
            ),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_unknown_property_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post(
            "/api/reservations/",
            _create_payload(a0_world, property_id=999999),
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        resp = api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.post("/api/reservations/", _create_payload(a0_world), format="json")
        assert resp.status_code == 403


class TestReservationList:
    """Added in A2: A0 shipped no way to list reservations at all."""

    @pytest.mark.django_db
    def test_happy_path_lists_reservations(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        created = api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.get("/api/reservations/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        ids = [r["id"] for r in resp.data["results"]]
        assert created.data["id"] in ids

    @pytest.mark.django_db
    def test_filters_by_status(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.get(
            "/api/reservations/",
            {"status": ReservationStatus.AWAITING_PAYMENT},
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 200
        assert resp.data["results"] == []
        assert resp.data["count"] == 0

    @pytest.mark.django_db
    def test_missing_tenant_context_returns_403(self, api, a0_world):
        grant_second_membership(a0_world["viewer"])
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        assert api.get("/api/reservations/").status_code == 403

    @pytest.mark.django_db
    def test_unauthenticated_returns_403(self, api, a0_world):
        assert (
            api.get("/api/reservations/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk)).status_code
            == 403
        )


class TestReservationDetailAndLifecycle:
    @pytest.mark.django_db
    def test_detail_happy_path(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        created = api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.get(f"/api/reservations/{created.data['id']}/", HTTP_X_TENANT_ID=str(tenant.pk))

        assert resp.status_code == 200
        assert resp.data["reservation_ref"] == created.data["reservation_ref"]

    @pytest.mark.django_db
    def test_unknown_reservation_is_404(self, api, a0_world):
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get("/api/reservations/999999/", HTTP_X_TENANT_ID=str(a0_world["tenant"].pk))
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_cross_tenant_reservation_is_404(self, api, a0_world):
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
        import datetime as _dt

        from apps.availability.services import AvailabilityService
        from apps.policies.services import PolicyService
        from apps.pricing.services import PricingService

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

        AvailabilityService.initialize_horizon(
            tenant_id=beta.id,
            property_id=beta_prop.id,
            room_type_id=beta_rt.id,
            total_units=5,
            start_date=a0_world["today"],
            horizon_days=5,
        )
        beta_reservation = ReservationService.reserve(
            tenant=beta,
            property=beta_prop,
            lines=[
                ReservationLineRequest(
                    room_type_id=beta_rt.id,
                    stay_period=StayPeriod(
                        a0_world["today"], a0_world["today"] + dt.timedelta(days=1)
                    ),
                    guest_count=GuestCount(adults=1, children=0),
                )
            ],
            idempotency_key="beta-key-1",
            guest_email="beta-guest@example.com",
        )

        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        resp = api.get(
            f"/api/reservations/{beta_reservation.pk}/",
            HTTP_X_TENANT_ID=str(a0_world["tenant"].pk),
        )

        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_request_payment_transitions_held_to_awaiting_payment(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        created = api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.post(
            f"/api/reservations/{created.data['id']}/request-payment/",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 200
        assert resp.data["status"] == ReservationStatus.AWAITING_PAYMENT

    @pytest.mark.django_db
    def test_request_payment_twice_is_409(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        created = api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )
        rid = created.data["id"]
        api.post(f"/api/reservations/{rid}/request-payment/", HTTP_X_TENANT_ID=str(tenant.pk))

        resp = api.post(
            f"/api/reservations/{rid}/request-payment/", HTTP_X_TENANT_ID=str(tenant.pk)
        )

        assert resp.status_code == 409

    @pytest.mark.django_db
    def test_cancel_hold(self, api, a0_world):
        tenant = a0_world["tenant"]
        _login(api, VIEWER_EMAIL, VIEWER_PASSWORD)
        created = api.post(
            "/api/reservations/",
            _create_payload(a0_world),
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        resp = api.post(
            f"/api/reservations/{created.data['id']}/cancel/",
            {},
            format="json",
            HTTP_X_TENANT_ID=str(tenant.pk),
        )

        assert resp.status_code == 200
        assert resp.data["status"] == ReservationStatus.CANCELLED
