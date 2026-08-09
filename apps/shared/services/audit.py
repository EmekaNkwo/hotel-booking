"""Audit logging — append-only, same-transaction records (M1.5, E8).

``AuditService.record`` writes one ``AuditLog`` row for a workflow transition,
policy decision, or sensitive mutation. It must be called INSIDE the same
transaction as the change it records — the audit entry and the change commit
or roll back together, so the log can never record something that didn't
happen, nor miss something that did.

References are TYPED: ``entity_type`` names the aggregate, ``entity_id`` its
pk as a string. Deliberately NOT a generic FK (E8) — no GFK indirection, no
polymorphic integrity hole, and queries can still target
``(entity_type, entity_id)`` directly via the composite index.
"""

from apps.shared.models import AuditLog


class AuditService:
    """Writes append-only audit entries within the caller's transaction."""

    @staticmethod
    def record(
        *,
        tenant_id: int,
        entity_type: str,
        entity_id: str,
        action: str,
        before: dict | None = None,
        after: dict | None = None,
        actor=None,
        reason: str = "",
        request_id: str = "",
    ) -> AuditLog:
        return AuditLog.objects.create(
            tenant_id=tenant_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            actor=actor,
            reason=reason,
            request_id=request_id,
        )
