"""Idempotency records — the dedup spine for money/booking mutations (M1.4, FR-PAY-05).

One row per (tenant, scope, key). The key and its result are stored in the SAME
transaction as the mutation it guards, so a retry can never re-run a mutation
whose commit is uncertain. ``request_hash`` catches the real safety hazard: the
same key presented with DIFFERENT input is a caller bug, never a silent replay.
"""

import hashlib
import json

from django.db import models

from apps.shared.models.mixins import TenantScopedMixin, TimeStampedMixin
from apps.shared.models.recipes import partial_index, status_constraint


class IdempotencyStatus(models.TextChoices):
    IN_PROGRESS = "in_progress", "In progress"
    COMPLETED = "completed", "Completed"


class IdempotencyRecord(TenantScopedMixin, TimeStampedMixin):
    """Dedup record for an idempotent mutation (DDS §22 ``idempotency_record``).

    ``scope`` namespaces the operation type (``payment.capture``,
    ``booking.confirm``); ``idempotency_key`` is the caller-supplied key;
    ``request_hash`` fingerprints the exact request so a key is only replayed
    for the request it originally served. Purged on ``expires_at`` (partial
    index) once the response is safe to forget.
    """

    scope = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=200)
    request_hash = models.CharField(max_length=64)  # sha256 hex of the canonical request
    response = models.JSONField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=IdempotencyStatus.choices, default=IdempotencyStatus.IN_PROGRESS
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "shared"
        db_table = "idempotency_record"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "scope", "idempotency_key"],
                name="idempotency_record_uq_tenant_scope_key",
            ),
            status_constraint("status", IdempotencyStatus, "idempotency_record_status_valid"),
        ]
        indexes = [
            partial_index(
                ["expires_at"],
                models.Q(expires_at__isnull=False),
                "idempotency_record_ix_expires",
            ),
        ]

    @staticmethod
    def fingerprint(payload: dict) -> str:
        """A stable sha256 of a canonical JSON payload (sorted keys, compact)."""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
