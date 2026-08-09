"""Idempotency — dedup spine for money/booking mutations (M1.4, FR-PAY-05).

``IdempotencyService.run`` executes a mutation exactly once per
``(tenant, scope, key)`` and replays the stored result for every retry. The
critical semantics: the idempotency record is created and the mutation runs in
the SAME transaction, so a failed mutation is never "remembered" as completed
(no replay of a failure), and a successful one is committed atomically with
its stored response.

``request_hash`` is the safety net: the same key replayed with DIFFERENT
input is a caller bug and raises ``IdempotencyKeyConflict`` rather than
silently returning a result computed for different arguments.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.shared.exceptions import IdempotencyInProgress, IdempotencyKeyConflict
from apps.shared.models import IdempotencyRecord, IdempotencyStatus


class IdempotencyService:
    """Guards one idempotent mutation scope (e.g. ``booking.confirm``)."""

    def __init__(self, *, tenant_id: int, scope: str):
        self.tenant_id = tenant_id
        self.scope = scope

    def run(
        self,
        key: str,
        request_payload: dict,
        *,
        execute,
        ttl_seconds: int | None = None,
    ) -> dict:
        """Execute ``execute()`` once per ``(scope, key)``; replay thereafter.

        ``request_payload`` is the canonical request the key covers (its hash
        detects key-reuse with different input). ``execute`` returns a
        JSON-serializable dict, stored verbatim as the replayable response.
        """
        request_hash = IdempotencyRecord.fingerprint(request_payload)
        existing = IdempotencyRecord.objects.filter(
            tenant_id=self.tenant_id,
            scope=self.scope,
            idempotency_key=key,
        ).first()
        if existing is not None:
            return self._replay(existing, request_hash)

        # First request: run the mutation and store key + result together.
        expires_at = (
            timezone.now() + timezone.timedelta(seconds=ttl_seconds)
            if ttl_seconds is not None
            else None
        )
        try:
            with transaction.atomic():
                record = IdempotencyRecord.objects.create(
                    tenant_id=self.tenant_id,
                    scope=self.scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    status=IdempotencyStatus.IN_PROGRESS,
                    expires_at=expires_at,
                )
                response = execute()
                record.response = response
                record.status = IdempotencyStatus.COMPLETED
                record.save(update_fields=["response", "status", "updated_at"])
            return response
        except IntegrityError:
            # A concurrent request created the record between our read and
            # insert — fall through to the replay/in-progress path.
            existing = IdempotencyRecord.objects.get(
                tenant_id=self.tenant_id, scope=self.scope, idempotency_key=key
            )
            return self._replay(existing, request_hash)

    def _replay(self, record: IdempotencyRecord, request_hash: str) -> dict:
        if record.status == IdempotencyStatus.IN_PROGRESS:
            raise IdempotencyInProgress(
                f"key {self.scope}/{record.idempotency_key} is still being processed"
            )
        if record.request_hash != request_hash:
            raise IdempotencyKeyConflict(
                f"idempotency key {self.scope}/{record.idempotency_key} was already "
                f"used with different request input"
            )
        return record.response
