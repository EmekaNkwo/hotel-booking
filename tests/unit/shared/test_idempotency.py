"""Unit tests for the idempotency service (M1.4, FR-PAY-05).

Order: first-run stores key+result in one transaction → replay returns the
stored result → same key + different input conflicts → in-progress handling →
same-transaction atomicity (a failed mutation is never remembered).
"""

import pytest
from django.db import transaction

from apps.shared.exceptions import IdempotencyInProgress, IdempotencyKeyConflict
from apps.shared.models import IdempotencyRecord, IdempotencyStatus
from apps.shared.services.idempotency import IdempotencyService

TENANT = 7
SCOPE = "booking.confirm"


@pytest.fixture(autouse=True)
def _clean():
    yield
    IdempotencyRecord.objects.all().delete()


class TestFirstRun:
    @pytest.mark.django_db
    def test_executes_the_mutation_and_stores_the_result(self):
        calls = []

        def mutate():
            calls.append(1)
            return {"status": "confirmed", "booking_id": 42}

        result = IdempotencyService(tenant_id=TENANT, scope=SCOPE).run(
            "key-1", {"booking_id": 42}, execute=mutate
        )

        assert result == {"status": "confirmed", "booking_id": 42}
        assert calls == [1]  # executed exactly once
        record = IdempotencyRecord.objects.get()
        assert record.status == IdempotencyStatus.COMPLETED
        assert record.response == result

    @pytest.mark.django_db
    def test_request_hash_fingerprints_the_payload(self):
        assert (
            IdempotencyRecord.fingerprint({"b": 1, "a": [2]})
            == IdempotencyRecord.fingerprint({"a": [2], "b": 1})
        )  # canonical: key order and whitespace don't matter


class TestReplay:
    @pytest.mark.django_db
    def test_retry_returns_stored_result_without_rerunning(self):
        calls = []

        def mutate():
            calls.append(1)
            return {"status": "confirmed"}

        service = IdempotencyService(tenant_id=TENANT, scope=SCOPE)
        first = service.run("key-1", {"id": 1}, execute=mutate)
        second = service.run("key-1", {"id": 1}, execute=mutate)

        assert first == second == {"status": "confirmed"}
        assert calls == [1]  # the mutation ran once, the retry replayed

    @pytest.mark.django_db
    def test_same_key_different_input_is_a_conflict_not_a_replay(self):
        service = IdempotencyService(tenant_id=TENANT, scope=SCOPE)
        service.run("key-1", {"booking_id": 42}, execute=lambda: {"ok": True})

        with pytest.raises(IdempotencyKeyConflict):
            service.run("key-1", {"booking_id": 99}, execute=lambda: {"ok": True})

    @pytest.mark.django_db
    def test_keys_are_scoped_so_the_same_key_used_in_two_scopes_is_independent(self):
        def mutate():
            return {"ok": True}

        service_a = IdempotencyService(tenant_id=TENANT, scope="payment.capture")
        service_b = IdempotencyService(tenant_id=TENANT, scope="booking.confirm")
        service_a.run("shared-key", {"x": 1}, execute=mutate)
        service_b.run("shared-key", {"x": 1}, execute=mutate)

        assert IdempotencyRecord.objects.count() == 2


class TestConcurrency:
    @pytest.mark.django_db
    def test_in_progress_record_raises_idempotency_in_progress(self):
        # A record stuck IN_PROGRESS (the original request died mid-flight)
        # signals "retryable, still running" rather than replaying nothing.
        IdempotencyService(tenant_id=TENANT, scope=SCOPE).run(
            "key-1", {"id": 1}, execute=lambda: {"ok": True}
        )
        IdempotencyRecord.objects.filter(idempotency_key="key-1").update(
            status=IdempotencyStatus.IN_PROGRESS, response=None
        )

        with pytest.raises(IdempotencyInProgress):
            IdempotencyService(tenant_id=TENANT, scope=SCOPE).run(
                "key-1", {"id": 1}, execute=lambda: {"ok": True}
            )

    @pytest.mark.django_db
    def test_failed_mutation_is_not_remembered_as_completed(self):
        # The store-key-and-result-in-the-same-transaction contract: if the
        # mutation raises, the IN_PROGRESS record rolls back with it, so a
        # retry re-runs the mutation instead of replaying a failure.
        attempts = []

        def flaky():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first attempt failed")
            return {"ok": True}

        service = IdempotencyService(tenant_id=TENANT, scope=SCOPE)
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                service.run("key-1", {"id": 1}, execute=flaky)

        # Nothing was committed: no record, no stored failure to replay.
        assert IdempotencyRecord.objects.count() == 0

        result = service.run("key-1", {"id": 1}, execute=flaky)
        assert result == {"ok": True}
        assert attempts == [1, 1]  # ran twice because the first never committed
