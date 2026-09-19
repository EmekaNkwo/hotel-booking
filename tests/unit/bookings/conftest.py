"""Booking test fixtures.

Reuses ``tenant``/``property`` from ``tests/unit/conftest.py``; ``room_type``,
``rate_plan``, and ``deposit_policy`` mirror the shape
``tests/unit/reservations/conftest.py`` established for M8, so a reservation
can be built and driven all the way to ``Awaiting_Payment``.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.availability.services import AvailabilityService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import RoomType
from apps.shared.value_objects import GuestCount, StayPeriod
from apps.tenants.models import Tenant


@pytest.fixture
def tenant2():
    return Tenant.objects.create(code="globex", name="Globex Hotels", base_currency="NGN")


@pytest.fixture
def room_type(tenant):
    return RoomType.objects.create(
        tenant=tenant,
        code="STD-KING",
        name="Standard King",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
    )


@pytest.fixture
def rate_plan(tenant, property, room_type):
    plan = PricingService.create_rate_plan(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="STD-RACK",
        base_rate_minor_units=10000,
        currency=property.currency,
    )
    return PricingService.activate_rate_plan(plan)


@pytest.fixture
def deposit_policy(tenant):
    draft = PolicyService.create_draft(
        tenant,
        "deposit",
        {"required": False},
        date(2020, 1, 1),
    )
    return PolicyService.publish(draft.id)


@pytest.fixture
def today():
    return timezone.now().date()


@pytest.fixture
def stay(today):
    return StayPeriod(today, today + timedelta(days=2))


@pytest.fixture(autouse=True)
def _capacity(tenant, property, room_type, rate_plan, deposit_policy, today):
    AvailabilityService.initialize_horizon(
        tenant_id=tenant.id,
        property_id=property.id,
        room_type_id=room_type.id,
        total_units=5,
        start_date=today,
        horizon_days=10,
    )


@pytest.fixture
def awaiting_payment_reservation(tenant, property, room_type, stay):
    """A reservation held then moved to Awaiting_Payment — ready to confirm."""
    line = ReservationLineRequest(
        room_type_id=room_type.id,
        stay_period=stay,
        guest_count=GuestCount(adults=2, children=0),
        quantity=1,
    )
    reservation = ReservationService.reserve(
        tenant=tenant,
        property=property,
        lines=[line],
        idempotency_key="fixture-reserve",
        guest_email="guest@example.com",
    )
    ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
    reservation.refresh_from_db()
    return reservation
