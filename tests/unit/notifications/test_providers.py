"""FakeEmailProvider unit tests (M13) — no Django DB needed."""

import pytest

from apps.notifications.providers import FakeEmailProvider, ProviderDeliveryError


@pytest.mark.django_db
class TestFakeEmailProvider:
    def test_send_succeeds_and_returns_a_provider_ref(self):
        provider = FakeEmailProvider()
        ref = provider.send(to="a@example.com", subject="s", body="b", idempotency_key="k1")
        assert ref == "fake-k1"

    def test_deterministic_failure_via_constructor(self):
        provider = FakeEmailProvider(fail_keys={"k1"})
        with pytest.raises(ProviderDeliveryError):
            provider.send(to="a@example.com", subject="s", body="b", idempotency_key="k1")

    def test_fail_next_fails_once_then_clears(self):
        provider = FakeEmailProvider()
        provider.fail_next("k1")
        with pytest.raises(ProviderDeliveryError):
            provider.send(to="a@example.com", subject="s", body="b", idempotency_key="k1")
        # Second attempt with the same key succeeds — the failure was consumed.
        ref = provider.send(to="a@example.com", subject="s", body="b", idempotency_key="k1")
        assert ref == "fake-k1"

    def test_duplicate_send_with_same_key_does_not_resend(self):
        provider = FakeEmailProvider()
        first = provider.send(to="a@example.com", subject="s1", body="b1", idempotency_key="k1")
        second = provider.send(to="a@example.com", subject="s2", body="b2", idempotency_key="k1")
        assert first == second
        assert len(provider.sent_messages()) == 1
        # The FIRST payload wins — a duplicate call never overwrites the
        # logical send that already happened.
        assert provider.sent_messages()["k1"]["subject"] == "s1"

    def test_different_keys_are_independent_sends(self):
        provider = FakeEmailProvider()
        provider.send(to="a@example.com", subject="s1", body="b1", idempotency_key="k1")
        provider.send(to="a@example.com", subject="s2", body="b2", idempotency_key="k2")
        assert len(provider.sent_messages()) == 2
