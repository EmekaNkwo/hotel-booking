"""Exceptions for the Shared Kernel's Django (persistence) layer.

These sit alongside the framework-free value-object exceptions
(apps/shared/value_objects/exceptions.py) but are deliberately separate: the
VO exceptions guard in-memory value construction, while these guard entity
persistence. Both are catchable independently of each other.
"""


class ConcurrencyError(Exception):
    """A versioned save() found the row changed since it was loaded.

    Raised when ``UPDATE ... WHERE id = ? AND version = <as-loaded>`` matched
    zero rows — another writer committed first. The caller should reload the
    row and re-apply its change (or surface "someone else changed this").
    """


class AppendOnlyViolation(Exception):
    """A write to an append-only log was attempted.

    ``domain_event`` and ``audit_log`` are immutable records: rows are created
    once, then never updated or deleted. The ORM refuses both; the database
    trigger/RLS layer (M2) is the schema-level guarantee behind it.
    """


class TransitionNotAllowed(Exception):
    """A workflow transition was attempted that the state machine does not allow.

    Raised by the WorkflowRunner when a transition is undefined for the entity's
    current state, or when the transition's guard rejects it. Mirrors
    django-fsm's ``TransitionNotAllowed`` semantics at the substrate boundary.
    """


class IdempotencyError(Exception):
    """Base class for idempotency-record failures."""


class IdempotencyKeyConflict(IdempotencyError):
    """The same idempotency key was used with a different request body.

    A key may be replayed only for the exact request it originally served;
    reusing it for different input is a caller bug, never a silent replay.
    """


class IdempotencyInProgress(IdempotencyError):
    """The idempotency key is already being processed by a concurrent request.

    Callers should surface this as a retryable condition (or wait) — the
    original operation is still running under the same key.
    """

