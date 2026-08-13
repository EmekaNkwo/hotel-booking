"""Property model tests (M3)."""

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.utils import IntegrityError

from apps.properties.models import Building, Facility, Floor, MediaAsset, Property, PropertyGroup


class TestPropertyGroup:
    @pytest.mark.django_db
    def test_create_property_group(self, tenant):
        """PropertyGroup creation and tenant scoping."""
        group = PropertyGroup.objects.create(tenant=tenant, name="Acme Hotels")
        assert group.name == "Acme Hotels"
        assert group.tenant == tenant

    @pytest.mark.django_db
    def test_property_group_unique_per_tenant(self, tenant):
        """Unique constraint: (tenant, name)."""
        PropertyGroup.objects.create(tenant=tenant, name="Group1")
        with pytest.raises(Exception):  # UniqueConstraint violation
            PropertyGroup.objects.create(tenant=tenant, name="Group1")


class TestProperty:
    @pytest.mark.django_db
    def test_create_property(self, tenant):
        """Property creation with all required fields."""
        property_obj = Property.objects.create(
            tenant=tenant,
            code="HOTEL001",
            name="Grand Hotel",
            status=Property.Status.ACTIVE,
            currency="USD",
            timezone="America/New_York",
            check_in_time="15:00:00",
            check_out_time="11:00:00",
            latitude=40.7128,
            longitude=-74.0060,
        )
        assert property_obj.code == "HOTEL001"
        assert property_obj.status == Property.Status.ACTIVE

    @pytest.mark.django_db
    def test_property_unique_code_per_tenant(self, tenant):
        """Unique constraint: (tenant, code)."""
        Property.objects.create(
            tenant=tenant,
            code="HOTEL001",
            name="Hotel 1",
            status=Property.Status.ACTIVE,
            currency="USD",
            timezone="UTC",
            check_in_time="14:00:00",
            check_out_time="12:00:00",
        )
        with pytest.raises(Exception):  # UniqueConstraint violation
            Property.objects.create(
                tenant=tenant,
                code="HOTEL001",
                name="Hotel 2",
                status=Property.Status.ACTIVE,
                currency="USD",
                timezone="UTC",
                check_in_time="14:00:00",
                check_out_time="12:00:00",
            )

    @pytest.mark.django_db
    def test_property_status_validation(self, tenant):
        """Status must be one of: draft, active, deactivated (DB CHECK constraint)."""
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Property.objects.create(
                    tenant=tenant,
                    code="HOTEL001",
                    name="Hotel",
                    status="invalid",  # Not in choices
                    currency="USD",
                    timezone="UTC",
                    check_in_time="14:00:00",
                    check_out_time="12:00:00",
                )

    @pytest.mark.django_db
    def test_latitude_longitude_validation(self, tenant):
        """Latitude [-90, 90], longitude [-180, 180]."""
        # Valid
        Property.objects.create(
            tenant=tenant,
            code="HOTEL001",
            name="Hotel",
            status=Property.Status.ACTIVE,
            currency="USD",
            timezone="UTC",
            check_in_time="14:00:00",
            check_out_time="12:00:00",
            latitude=40.7128,
            longitude=-74.0060,
        )
        # Invalid latitude
        with pytest.raises(ValidationError):
            Property.objects.create(
                tenant=tenant,
                code="HOTEL002",
                name="Hotel",
                status=Property.Status.ACTIVE,
                currency="USD",
                timezone="UTC",
                check_in_time="14:00:00",
                check_out_time="12:00:00",
                latitude=100,  # > 90
                longitude=-74.0060,
            )


class TestBuilding:
    @pytest.mark.django_db
    def test_create_building(self, tenant, property):
        """Building creation with property FK."""
        building = Building.objects.create(
            tenant=tenant,
            property=property,
            code="BLDG-A",
            name="Main Building",
        )
        assert building.property == property

    @pytest.mark.django_db
    def test_building_unique_code_per_property(self, tenant, property):
        """Unique constraint: (property, code)."""
        Building.objects.create(
            tenant=tenant,
            property=property,
            code="BLDG-A",
            name="Building A",
        )
        with pytest.raises(Exception):  # UniqueConstraint violation
            Building.objects.create(
                tenant=tenant,
                property=property,
                code="BLDG-A",
                name="Building B",
            )


class TestFloor:
    @pytest.mark.django_db
    def test_create_floor(self, tenant, building):
        """Floor creation with building FK."""
        floor = Floor.objects.create(
            tenant=tenant,
            building=building,
            name="1",
        )
        assert floor.building == building

    @pytest.mark.django_db
    def test_floor_unique_name_per_building(self, tenant, building):
        """Unique constraint: (building, name)."""
        Floor.objects.create(tenant=tenant, building=building, name="1")
        with pytest.raises(Exception):  # UniqueConstraint violation
            Floor.objects.create(tenant=tenant, building=building, name="1")


class TestFacility:
    @pytest.mark.django_db
    def test_create_facility(self, tenant, property):
        """Facility creation with property FK."""
        facility = Facility.objects.create(
            tenant=tenant,
            property=property,
            facility_type="restaurant",
            name="Main Dining",
        )
        assert facility.property == property

    @pytest.mark.django_db
    def test_facility_unique_per_property_and_type(self, tenant, property):
        """Unique constraint: (property, facility_type, name)."""
        Facility.objects.create(
            tenant=tenant,
            property=property,
            facility_type="restaurant",
            name="Main Dining",
        )
        with pytest.raises(Exception):  # UniqueConstraint violation
            Facility.objects.create(
                tenant=tenant,
                property=property,
                facility_type="restaurant",
                name="Main Dining",
            )


class TestMediaAsset:
    @pytest.mark.django_db
    def test_create_media_asset(self, tenant, property):
        """MediaAsset creation with property FK."""
        asset = MediaAsset.objects.create(
            tenant=tenant,
            property=property,
            object_key="photos/hotel001/exterior.jpg",
            kind=MediaAsset.Kind.PHOTO,
            title="Exterior View",
            metadata={"width": 1920, "height": 1080},
        )
        assert asset.property == property
        assert asset.kind == MediaAsset.Kind.PHOTO

    @pytest.mark.django_db
    def test_media_asset_unique_object_key(self, tenant, property):
        """Unique constraint: object_key."""
        MediaAsset.objects.create(
            tenant=tenant,
            property=property,
            object_key="photos/hotel001/exterior.jpg",
            kind=MediaAsset.Kind.PHOTO,
        )
        with pytest.raises(Exception):  # UniqueConstraint violation
            MediaAsset.objects.create(
                tenant=tenant,
                property=property,
                object_key="photos/hotel001/exterior.jpg",  # Duplicate
                kind=MediaAsset.Kind.PHOTO,
            )