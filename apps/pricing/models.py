"""Pricing models (M6, DDS S8).

``RatePlan`` is the sellable product definition; ``RateOverride`` and
``RateModifier`` feed it. Price is computed ONLY by ``PricingService.price()``
(DR-06) — nothing here computes a price. All three follow the M3/M5
convention: ``EntityMixin`` (timestamps + tenant + optimistic ``version``,
matching DDS A.6's "optimistic (`version`)" bucket for rate edits) with an
explicit ``tenant`` FK overriding the mixin's bare ``tenant_id``.

``RateOverride.start_date``/``end_date`` are **inclusive on both ends**
(``[start_date, end_date]``) — a deliberate departure from the Shared
Kernel's half-open ``DateRange``/``StayPeriod`` convention, because DDS
S8 explicitly requires ``daterange(start_date, end_date, '[]')`` for the
non-overlap guarantee. Reusing ``DateRange`` here would silently misrepresent
that inclusive semantic, so these are plain ``DateField``s instead.
"""

from django.db import models

from apps.shared.models.mixins import EntityMixin
from apps.shared.models.recipes import status_constraint
from apps.shared.tenancy import TenantScopedManager


class RatePlanStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    RETIRED = "retired", "Retired"


class AdjustmentType(models.TextChoices):
    ABSOLUTE = "absolute", "Absolute"
    PERCENT = "percent", "Percent"


class ModifierType(models.TextChoices):
    SEASON = "season", "Season"
    WEEKEND = "weekend", "Weekend"
    HOLIDAY = "holiday", "Holiday"
    LONG_STAY = "long_stay", "Long stay"
    CORPORATE = "corporate", "Corporate"


class RatePlan(EntityMixin):
    """The sellable product: room-type x base rate x policy refs (DDS S8)."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="rate_plans",
    )
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.RESTRICT,
        related_name="rate_plans",
    )
    room_type = models.ForeignKey(
        "rooms.RoomType",
        on_delete=models.RESTRICT,
        related_name="rate_plans",
    )
    code = models.CharField(max_length=32)
    base_rate_minor_units = models.BigIntegerField()
    currency = models.CharField(max_length=3)  # ISO 4217; must equal property.currency
    status = models.CharField(
        max_length=16,
        choices=RatePlanStatus.choices,
        default=RatePlanStatus.DRAFT,
    )
    sellable = models.BooleanField(default=True)
    # {"cancellation_policy_id": int, "deposit_policy_id": int} — refs only,
    # never policy content (DR-10: Pricing asks Policy, never embeds it).
    policy_refs = models.JSONField(default=dict, blank=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            status_constraint("status", RatePlanStatus, "rate_plan_valid_status"),
            models.CheckConstraint(
                condition=models.Q(base_rate_minor_units__gte=0),
                name="rate_plan_base_rate_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(currency__regex=r"^[A-Z]{3}$"),
                name="rate_plan_currency_iso3",
            ),
            models.UniqueConstraint(
                fields=["property", "code"],
                name="rate_plan_uq_property_code",
            ),
        ]
        indexes = [
            models.Index(fields=["property", "status"]),
            models.Index(fields=["room_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.status})"


class RateOverride(EntityMixin):
    """A per-date-range price adjustment on a rate plan. Dates are inclusive
    on both ends (see module docstring)."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="rate_overrides",
    )
    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.RESTRICT,
        related_name="overrides",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    adjustment_type = models.CharField(max_length=16, choices=AdjustmentType.choices)
    adjustment_minor_units = models.BigIntegerField()
    active = models.BooleanField(default=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            status_constraint(
                "adjustment_type", AdjustmentType, "rate_override_valid_adjustment_type"
            ),
            models.CheckConstraint(
                condition=~models.Q(adjustment_minor_units=0),
                name="rate_override_adjustment_nonzero",
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="rate_override_end_on_or_after_start",
            ),
            # The GiST EXCLUDE for real non-overlap is Postgres-only and
            # applied out-of-band in 0003_exclude_rate_override_overlap.py —
            # ExclusionConstraint has no vendor guard and would break the
            # SQLite unit tier if declared here (see that migration's
            # docstring). RateService additionally enforces the same
            # inclusive-range overlap rule in Python for every backend.
        ]
        indexes = [
            models.Index(fields=["rate_plan", "start_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.rate_plan_id}: {self.start_date}..{self.end_date} ({self.adjustment_type})"


class RateModifier(EntityMixin):
    """A calendar/segment modifier as data (R3). ``config`` shape is fixed
    per ``modifier_type`` — see ``apps.pricing.services`` for the exact,
    documented contract each type evaluates against."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.RESTRICT,
        related_name="rate_modifiers",
    )
    rate_plan = models.ForeignKey(
        RatePlan,
        on_delete=models.RESTRICT,
        related_name="modifiers",
    )
    modifier_type = models.CharField(max_length=16, choices=ModifierType.choices)
    config = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    objects = TenantScopedManager()

    class Meta:
        constraints = [
            status_constraint("modifier_type", ModifierType, "rate_modifier_valid_type"),
        ]
        indexes = [
            models.Index(fields=["rate_plan", "modifier_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.rate_plan_id}: {self.modifier_type}"
