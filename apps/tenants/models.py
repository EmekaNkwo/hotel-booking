"""Tenancy models (DMS §2).

``Tenant`` is the boundary of all tenant-scoped data and the unit of
provisioning/suspension/decommission (FR-TEN-01, SDD §13.4). It is
**platform-scoped** — deliberately no ``tenant_id`` (SDD §13.3: platform data
never lives inside a tenant's namespace) — so it uses the lifecycle mixins but
not ``TenantScopedMixin``. ``base_currency`` is the anchor for the M1 ``Money``
value object; the regex check mirrors ``^[A-Z]{3}$`` at the schema level.
"""

from django.db import models

from apps.shared.models import TimeStampedMixin, VersionedMixin
from apps.shared.models.recipes import status_constraint


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
