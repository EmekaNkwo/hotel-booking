"""Notification test fixtures.

Reuses ``tenant``/``property`` from ``tests/unit/conftest.py``. Builds all
the way up the stack (RoomType -> Availability -> Reservation) via
``make_reservation`` and publishes it through the real outbox relay, so a
notifiable ``DomainEvent`` is a one-call ask.
"""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.availability.services import AvailabilityService
from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import RoomType
from apps.shared.services.outbox import OutboxRelay
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


def make_reservation(tenant, property, room_type, stay, *, guest_email, key_prefix):
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
    OutboxRelay().publish_batch()
    return reservation


@pytest.fixture
def reservation(tenant, property, room_type, stay):
    return make_reservation(
        tenant,
        property,
        room_type,
        stay,
        guest_email="guest@example.com",
        key_prefix="fixture",
    )


@pytest.fixture
def reservation_created_template(tenant):
    from apps.notifications.models import NotificationTemplate, TemplateStatus

    return NotificationTemplate.objects.create(
        tenant=tenant,
        notification_type="reservation_created",
        channel="email",
        locale="en",
        subject="Your reservation {reservation_ref}",
        body="Hi {guest_name}!",
        status=TemplateStatus.PUBLISHED,
    )
