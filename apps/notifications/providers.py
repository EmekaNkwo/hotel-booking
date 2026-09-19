"""Email provider adapter (M13). No real SMTP/vendor integration —
``FakeEmailProvider`` is the only implementation, deterministic and
in-memory, standing in for the "integrations" seam DDS/roadmap describe.

The defensible guarantee this whole app builds toward is NOT "exactly-once
external delivery" (no fake provider can prove that about a real vendor) —
it's "at-most-one logical NotificationJob per source event/channel, one
successful logical delivery state, retry-safe worker processing." The
``idempotency_key`` parameter here exists so a provider CAN detect a
duplicate send if the same job is ever retried after its external call
already succeeded (e.g. a crash between the provider call and the DB
transition that records it) — real providers commonly support exactly this.
"""

from typing import Protocol


class ProviderDeliveryError(Exception):
    """The provider rejected or failed to complete a send."""


class EmailProvider(Protocol):
    def send(self, *, to: str, subject: str, body: str, idempotency_key: str) -> str:
        """Return a provider-assigned reference on success; raise
        ``ProviderDeliveryError`` on failure."""
        ...


class FakeEmailProvider:
    """Deterministic, in-memory fake. Supports:

    - success (the default) — returns a synthetic ``provider_ref``.
    - deterministic failure — pass ``fail_keys`` (a set of idempotency keys
      that should raise) at construction, or call ``fail_next()``.
    - duplicate/idempotency detection — a ``send()`` reusing an
      ``idempotency_key`` that already succeeded returns the SAME
      ``provider_ref`` without re-recording a second logical send.
    """

    def __init__(self, *, fail_keys: set[str] | None = None):
        self._sent: dict[str, dict] = {}
        self._fail_keys: set[str] = set(fail_keys or ())

    def fail_next(self, idempotency_key: str) -> None:
        """Mark ``idempotency_key`` to fail on its next (or first) attempt."""
        self._fail_keys.add(idempotency_key)

    def sent_messages(self) -> dict[str, dict]:
        """Read-only view of every logical send this instance recorded —
        test/introspection helper only."""
        return dict(self._sent)

    def send(self, *, to: str, subject: str, body: str, idempotency_key: str) -> str:
        if idempotency_key in self._sent:
            # Duplicate call for an already-succeeded key: return the SAME
            # reference, never a second logical send.
            return self._sent[idempotency_key]["provider_ref"]
        if idempotency_key in self._fail_keys:
            self._fail_keys.discard(idempotency_key)
            raise ProviderDeliveryError(f"simulated failure for {idempotency_key!r}")
        provider_ref = f"fake-{idempotency_key}"
        self._sent[idempotency_key] = {
            "to": to,
            "subject": subject,
            "body": body,
            "provider_ref": provider_ref,
        }
        return provider_ref
