"""Property hierarchy models (M3).

Tenant-scoped property catalog: Property, PropertyGroup, Building, Floor, Facility, MediaAsset.
No PostGIS in M3 — uses latitude/longitude with basic B-tree index (not true proximity search).
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

from apps.shared.models.mixins import EntityMixin
from apps.shared.tenancy import TenantScopedManager


class PropertyGroup(EntityMixin):
    """Multi-property container (e.g., Maria's hotel group)."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="property_groups",
    )
    name = models.CharField(max_length=128)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="unique_property_group_per_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant"]),
        ]

    def __str__(self):
        return f"{self.name} (group)"


class Property(EntityMixin):
    """Operational unit (hotel)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        DEACTIVATED = "deactivated", "Deactivated"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="properties",
    )
    property_group = models.ForeignKey(
        PropertyGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="properties",
    )
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=128)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    currency = models.CharField(max_length=3)  # ISO 4217
    timezone = models.CharField(max_length=64)  # IANA timezone
    check_in_time = models.TimeField()
    check_out_time = models.TimeField()
    # Non-PostGIS location (M3 temporary representation)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    deactivated_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "code"],
                name="unique_property_code_per_tenant",
            ),
            models.CheckConstraint(
                check=models.Q(status__in=["draft", "active", "deactivated"]),
                name="property_valid_status",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            # Basic B-tree index for filtering (NOT true proximity search)
            # Geographic distance/search semantics deferred to future PostGIS milestone
            models.Index(fields=["latitude", "longitude"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Building(EntityMixin):
    """Building within a property."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="buildings",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.RESTRICT,
        related_name="buildings",
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "code"],
                name="unique_building_code_per_property",
            ),
        ]
        indexes = [
            models.Index(fields=["property"]),
        ]

    def __str__(self):
        return f"{self.property.code}:{self.code} ({self.name})"


class Floor(EntityMixin):
    """Floor within a building."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="floors",
    )
    building = models.ForeignKey(
        Building,
        on_delete=models.RESTRICT,
        related_name="floors",
    )
    name = models.CharField(max_length=32)  # e.g., "1", "2", "Lobby", "Penthouse"
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["building", "name"],
                name="unique_floor_name_per_building",
            ),
        ]
        indexes = [
            models.Index(fields=["building"]),
        ]

    def __str__(self):
        return f"{self.building.property.code}:{self.building.code}:{self.name}"


class Facility(EntityMixin):
    """Amenity instance (feeds Search facets)."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="facilities",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.RESTRICT,
        related_name="facilities",
    )
    facility_type = models.CharField(max_length=64)  # e.g., "restaurant", "pool", "gym"
    name = models.CharField(max_length=128)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "facility_type", "name"],
                name="unique_facility_per_property_and_type",
            ),
        ]
        indexes = [
            models.Index(fields=["property"]),
        ]

    def __str__(self):
        return f"{self.property.code}:{self.facility_type}:{self.name}"


class MediaAsset(EntityMixin):
    """Property media (images, videos). Stores object-storage key + metadata, never binary."""

    class Kind(models.TextChoices):
        PHOTO = "photo", "Photo"
        VIDEO = "video", "Video"
        FLOOR_PLAN = "floor_plan", "Floor Plan"
        VIRTUAL_TOUR = "virtual_tour", "Virtual Tour"

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="media_assets",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.RESTRICT,
        related_name="media_assets",
    )
    object_key = models.CharField(max_length=256, unique=True)  # S3/GCS key
    kind = models.CharField(max_length=32, choices=Kind.choices)
    title = models.CharField(max_length=128, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantScopedManager()

    class Meta:
        indexes = [
            models.Index(fields=["property", "kind"]),
        ]

    def __str__(self):
        return f"{self.property.code}:{self.kind}:{self.object_key}"