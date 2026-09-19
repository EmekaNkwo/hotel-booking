"""Reservation test fixtures.

Reuses ``tenant``/``property`` from ``tests/unit/conftest.py``. Adds a
``room_type`` (local, matching every other app's test-tier pattern), an
active ``rate_plan`` (M6) so ``PricingService.price()`` has something to
quote, and a published ``deposit`` policy (M4) so
``PolicyService.resolve(..., PolicyType.DEPOSIT, ...)`` never raises
``NoPolicyFound`` in ordinary reserve() tests.
"""

from datetime import date

import pytest

from apps.policies.services import PolicyService
from apps.pricing.services import PricingService
from apps.rooms.models import RoomType
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
        {"required": True, "amount": {"type": "percent", "value": 20}},
        date(2020, 1, 1),
    )
    return PolicyService.publish(draft.id)
