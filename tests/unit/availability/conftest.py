"""Availability/Inventory test fixtures.

Reuses ``tenant``/``property`` from ``tests/unit/conftest.py``.
"""

from datetime import date

import pytest

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
def horizon_start():
    """A fixed, deterministic start date for slot windows in unit tests."""
    return date(2026, 10, 1)
