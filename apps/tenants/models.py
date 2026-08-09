"""Tenancy models (DMS §2).

``Tenant`` is the boundary of all tenant-scoped data and the unit of
provisioning/suspension/decommission (FR-TEN-01, SDD §13.4). It is
**platform-scoped** — deliberately no ``tenant_id`` (SDD §13.3: platform data
never lives inside a tenant's namespace) — so it uses the lifecycle mixins but
not ``TenantScopedMixin``. ``base_currency`` is the anchor for the M1 ``Money``
value object; the regex check mirrors ``^[A-Z]{3}$`` at the schema level.
"""

from django.db import models

from apps.shared.models import TenantScopedMixin, TimeStampedMixin, VersionedMixin
from apps.shared.models.recipes import status_constraint
from apps.shared.tenancy import TenantScopedManager


class TenantStatus(models.TextChoices):
    """Lifecycle of a tenant (DDS §2, SDD §13.4)."""

    PROSPECTIVE = "prospective", "Prospective"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    DECOMMISSIONED = "decommissioned", "Decommissioned"


class Tenant(TimeStampedMixin, VersionedMixin):
    """The customer's boundary — identity, currency, lifecycle."""

    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    status = models.CharField(
        max_length=20,
        choices=TenantStatus.choices,
        default=TenantStatus.PROSPECTIVE,
    )
    base_currency = models.CharField(max_length=3)
    decommissioned_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        db_table = "tenant"
        verbose_name = "tenant"
        constraints = [
            status_constraint("status", TenantStatus, "tenant_status_valid"),
            models.CheckConstraint(
                condition=models.Q(base_currency__regex=r"^[A-Z]{3}$"),
                name="tenant_base_currency_iso3",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="tenant_ix_status"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


class TenantSettings(TimeStampedMixin, VersionedMixin):
    """1:1 mutable config for a tenant (DDS §2).

    The PK is the FK to ``tenant`` — exactly one settings row per tenant, and
    the ``tenant_id`` column doubles as the PK. The JSONB ``settings`` blob is
    the mutable part; versioned so concurrent configuration writes cannot
    silently overwrite each other.
    """

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.RESTRICT,
        primary_key=True,
        related_name="settings",
    )
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "tenant_settings"

    def __str__(self) -> str:
        return f"settings for tenant {self.tenant_id}"


class FeatureFlag(TenantScopedMixin, TimeStampedMixin):
    """Per-tenant capability toggle (DDS §2).

    ``flag_key`` is validated against the registry in ``apps.tenants.flags`` —
    no freeform keys (DMS #5). Soft-delete via ``deleted_at`` keeps history;
    the partial unique index guarantees one live row per (tenant, flag).
    """

    flag_key = models.CharField(max_length=60)
    enabled = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = TenantScopedManager()

    class Meta:
        db_table = "feature_flag"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "flag_key"],
                condition=models.Q(deleted_at__isnull=True),
                name="feature_flag_uq_tenant_key_active",
            )
        ]

    def __str__(self) -> str:
        return f"flag {self.flag_key}={self.enabled} @ tenant {self.tenant_id}"
