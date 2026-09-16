"""Pricing test fixtures.

Reuses ``tenant``/``property`` from ``tests/unit/conftest.py``. Adds
``room_type`` (local, matching ``tests/unit/rooms/conftest.py``'s pattern —
each app's test tier defines what it needs) and ``rate_plan`` (active, ready
to price against).
"""
import pytest

from apps.pricing.services import PricingService
from apps.rooms.models import RoomType
from apps.tenants.models import Tenant


@pytest.fixture
def tenant2():
    """A second tenant, distinct from ``tenant``, for isolation tests."""
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
    """An active rate plan: NGN 10,000/night."""
    plan = PricingService.create_rate_plan(
        tenant=tenant,
        property=property,
        room_type=room_type,
        code="STD-RACK",
        base_rate_minor_units=10000,
        currency=property.currency,
    )
    return PricingService.activate_rate_plan(plan)
