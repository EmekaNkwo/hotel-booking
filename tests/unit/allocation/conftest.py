"""Allocation test fixtures.

Reuses ``tenant``/``property`` from ``tests/unit/conftest.py``. Builds all
the way up the stack (RoomType -> RatePlan -> Policy -> Availability ->
Reservation -> Booking) so a confirmed, unallocated ``BookingLine`` is a
one-fixture ask — mirrors the ``awaiting_payment_reservation`` fixture shape
from ``tests/unit/bookings/conftest.py``.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.availability.services import AvailabilityService
from apps.bookings.services import BookingService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import Room, RoomType
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
    draft = PolicyService.create_draft(tenant, "deposit", {"required": False}, date(2020, 1, 1))
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


def make_booking_line(tenant, property, room_type, stay, *, guest_email, key_prefix):
    """Reserve -> request_payment -> confirm -> return the single BookingLine."""
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
        idempotency_key=f"{key_prefix}-reserve",
        guest_email=guest_email,
    )
    ReservationService.request_payment(reservation.id, tenant_id=reservation.tenant_id)
    booking = BookingService.confirm(
        tenant_id=tenant.id,
        reservation_id=reservation.id,
        idempotency_key=f"{key_prefix}-confirm",
    )
    return booking.lines.get()


@pytest.fixture
def confirmed_booking_line(tenant, property, room_type, stay):
    return make_booking_line(
        tenant,
        property,
        room_type,
        stay,
        guest_email="guest@example.com",
        key_prefix="fixture",
    )


@pytest.fixture
def vacant_room(tenant, property, room_type):
    return Room.objects.create(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="101",
        operational_state=Room.OperationalState.VACANT_CLEAN,
    )
