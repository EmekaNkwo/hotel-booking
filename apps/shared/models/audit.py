"""Audit log — append-only, same-transaction record of sensitive changes (M1.5, E8).

``entity_type``/``entity_id`` are TYPED refs (plain strings naming the
aggregate and its pk) — deliberately NOT a generic foreign key (E8): no GFK
indirection, no polymorphic integrity hole, queries can still target
``(entity_type, entity_id)`` directly. One row per workflow transition /
policy decision / sensitive mutation, written in the SAME transaction as the
change it records, immutable, and never editable by the actor it records.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.shared.models.mixins import AppendOnlyMixin, TenantScopedMixin


class AuditLog(AppendOnlyMixin, TenantScopedMixin):
    """Append-only audit trail (DDS §22 ``audit_log``).

    ``before``/``after`` are JSONB snapshots of the entity's relevant fields
    around the change (primitives only). ``actor`` is a real FK to
    ``accounts.UserAccount`` with ``SET NULL`` so history survives account
    deletion; ``request_id`` correlates the whole request. Partitioned by
    ``occurred_at`` and RLS-scoped in later milestones.
    """

    entity_type = models.CharField(max_length=100)  # e.g. "booking"
    entity_id = models.CharField(max_length=100)  # string form of the aggregate pk
    action = models.CharField(max_length=100)  # e.g. "update", "status.confirm"
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    reason = models.CharField(max_length=200, blank=True, default="")
    request_id = models.CharField(max_length=100, blank=True, default="")
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        app_label = "shared"
        db_table = "audit_log"
        indexes = [
            models.Index(
                fields=["entity_type", "entity_id", "-occurred_at"],
                name="audit_log_ix_entity_occurred",
            ),
            models.Index(fields=["actor_id", "-occurred_at"], name="audit_log_ix_actor"),
            models.Index(fields=["tenant_id", "-occurred_at"], name="audit_log_ix_tenant"),
        ]
