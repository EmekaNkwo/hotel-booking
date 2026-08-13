"""Fixtures shared across the unit tier (tests/unit/*).

Lives here, rather than in a single app's conftest, because more than one
app's fixtures depend on it (e.g. ``tests/unit/properties/conftest.py`` and
``tests/unit/rooms/conftest.py`` both build on a ``tenant``).
"""

import pytest

from apps.properties.models import Property
from apps.tenants.models import Tenant


@pytest.fixture
def tenant():
    """A minimal tenant for tests that only need a valid tenant_id."""
    return Tenant.objects.create(code="acme", name="Acme Hotels", base_currency="NGN")


@pytest.fixture
def property(tenant):
    """A minimal property, needed by both properties/ and rooms/ tests."""
    return Property.objects.create(
        tenant=tenant,
        code="TEST001",
        name="Test Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
        latitude=40.7128,
        longitude=-74.0060,
    )
