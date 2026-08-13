"""Property test fixtures.

The ``property`` fixture itself lives in tests/unit/conftest.py — it is
needed by both this package and tests/unit/rooms/.
"""

import pytest

from apps.properties.models import Building


@pytest.fixture
def property_group(tenant):
    """PropertyGroup fixture."""
    from apps.properties.models import PropertyGroup
    return PropertyGroup.objects.create(tenant=tenant, name="Test Group")


@pytest.fixture
def building(tenant, property):
    """Building fixture."""
    return Building.objects.create(
        tenant=tenant,
        property=property,
        code="BLDG-A",
        name="Main Building",
    )