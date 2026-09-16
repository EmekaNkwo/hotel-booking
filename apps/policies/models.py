from django.db import models
from django.db.models import F, Q
from django.db.models.fields.composite import CompositePrimaryKey

from apps.shared.tenancy import TenantScopedManager


class Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    RETIRED = "retired", "Retired"


class PolicyType(models.TextChoices):
    CANCELLATION = "cancellation", "Cancellation"
    REFUND = "refund", "Refund"
    DEPOSIT = "deposit", "Deposit"
    CHECK_IN = "check_in", "Check-in"
    CHECK_OUT = "check_out", "Check-out"
    CLEANING = "cleaning", "Cleaning"
    PRICING = "pricing", "Pricing"


class Policy(models.Model):
    """Policy row = one version (draft or published). Immutable after publish."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.RESTRICT)
    policy_type = models.CharField(max_length=16, choices=PolicyType.choices)
    version = models.PositiveSmallIntegerField(null=True, blank=True)  # NULL = draft
    status = models.CharField(max_length=16, choices=Status.choices)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    rules = models.JSONField(null=True, blank=True)
    property = models.ForeignKey(
        "properties.Property",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="policies",
    )
    name = models.CharField(max_length=128, blank=True, default="")
    description = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "accounts.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    objects = TenantScopedManager()

    def save(self, *args, **kwargs):
        """Enforce published-row immutability.

        Published rows cannot be mutated after publication.
        Only the retire() method may change status (via update_fields).
        """
        # Ensure name/description are never None (convert to empty string) —
        # both fields are blank=True, default="", but PolicyService.create_draft()
        # and publish() default their kwargs to None, which full_clean() lets
        # through (blank=True skips null-checking) straight into a NOT NULL column.
        if self.name is None:
            self.name = ""
        if self.description is None:
            self.description = ""
        if self.pk:
            try:
                existing = Policy.objects.get(pk=self.pk)
            except Policy.DoesNotExist:
                existing = None
            if existing and existing.status == Status.PUBLISHED:
                # Allow only status changes (retire)
                if self.status != Status.PUBLISHED:
                    super().save(*args, **kwargs)
                    return
                raise ValueError(
                    "Published policy rows are immutable. "
                    "Use PolicyService.retire() to change status."
                )
        super().save(*args, **kwargs)

    class Meta:
        app_label = "policies"
        constraints = [
            models.CheckConstraint(
                check=Q(effective_to__isnull=True) | Q(effective_from__lt=F("effective_to")),
                name="policy_effective_to_after_from",
            ),
            models.CheckConstraint(
                check=Q(version__gt=0) | Q(version__isnull=True),
                name="policy_version_positive",
            ),
            models.CheckConstraint(
                check=Q(status__in=["draft", "published", "retired"]),
                name="policy_valid_status",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "policy_type", "status"]),
            models.Index(fields=["tenant", "policy_type", "effective_from"]),
        ]

    def __str__(self):
        status = self.status
        version = f" v{self.version}" if self.version else ""
        return f"{self.get_policy_type_display()}{version} ({status})"


class PolicyEvaluationLog(models.Model):
    """Immutable log of every policy evaluation (auditability)."""
    evaluated_at = models.DateTimeField()
    id = models.BigIntegerField()
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.RESTRICT, db_index=True)
    policy = models.ForeignKey(Policy, on_delete=models.RESTRICT, db_index=True)
    context = models.JSONField(null=True, blank=True)
    answer = models.JSONField(null=True, blank=True)

    # Composite primary key per DDS §21 (evaluated_at, id)
    pk = CompositePrimaryKey("evaluated_at", "id")

    objects = TenantScopedManager()

    class Meta:
        app_label = "policies"
        indexes = [
            models.Index(fields=["policy", "evaluated_at"]),
            models.Index(fields=["tenant", "evaluated_at"]),
        ]