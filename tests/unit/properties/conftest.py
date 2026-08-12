"""Property test fixtures."""

import pytest

from apps.properties.models import Property, Building


@pytest.fixture
def property_group(tenant):
    """PropertyGroup fixture."""
    from apps.properties.models import PropertyGroup
    return PropertyGroup.objects.create(tenant=tenant, name="Test Group")


@pytest.fixture
def property(tenant):
    """Property fixture."""
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


@pytest.fixture
def building(tenant, property):
    """Building fixture."""
    return Building.objects.create(
        tenant=tenant,
        property=property,
        code="BLDG-A",
        name="Main Building",
    )