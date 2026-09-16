"""Policy lifecycle tests (M4)."""
import pytest
from datetime import date

from apps.policies.models import Policy, PolicyType, Status
from apps.policies.services import PolicyService, InvalidStateTransition, NoPolicyFound


@pytest.mark.django_db
class TestPolicyLifecycle:
    def test_create_draft(self, tenant):
        """Draft policy can be created with all required fields."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Standard Cancellation",
        )
        assert policy.status == Status.DRAFT
        assert policy.version is None
        assert policy.rules == {"allowed": True}

    def test_update_draft(self, tenant):
        """Draft policy rules can be updated before publishing."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        updated = PolicyService.update_draft(policy.id, rules={"allowed": False})
        assert updated.rules == {"allowed": False}
        assert updated.status == Status.DRAFT

    def test_publish_assigns_version(self, tenant):
        """Publishing assigns sequential version 1 to the first published version."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        published = PolicyService.publish(policy.id)
        assert published.status == Status.PUBLISHED
        assert published.version == 1
        assert published.published_at is not None

    def test_publish_discards_draft(self, tenant):
        """Publishing discards the draft row — only published version remains."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        PolicyService.publish(policy.id)
        assert not Policy.objects.filter(id=policy.id).exists()

    def test_published_immutable(self, tenant):
        """Published policy content cannot be mutated."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        published = PolicyService.publish(policy.id)
        published.rules = {"allowed": False}
        with pytest.raises(ValueError, match="immutable"):
            published.save()

    def test_retire_sets_status_and_effective_to(self, tenant):
        """Retiring sets status=RETIRED and fills effective_to if open-ended."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        published = PolicyService.publish(policy.id)
        retired = PolicyService.retire(published.id)
        assert retired.status == Status.RETIRED
        assert retired.effective_to is not None

    def test_retired_content_unchanged(self, tenant):
        """Retiring preserves all historical content."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True, "penalty_type": "nightly_rate"},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        published = PolicyService.publish(policy.id)
        retired = PolicyService.retire(published.id)
        assert retired.rules == {"allowed": True, "penalty_type": "nightly_rate"}
        assert retired.effective_from == date(2026, 1, 1)
        assert retired.version == 1

    def test_publish_published_raises(self, tenant):
        """Publishing an already-published policy raises InvalidStateTransition."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        published = PolicyService.publish(policy.id)
        with pytest.raises(InvalidStateTransition):
            PolicyService.publish(published.id)

    def test_retire_draft_raises(self, tenant):
        """Retiring a draft raises InvalidStateTransition."""
        policy = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        with pytest.raises(InvalidStateTransition):
            PolicyService.retire(policy.id)

    def test_second_draft_replaces_first(self, tenant):
        """Creating a new draft for same (tenant, type) deletes the previous draft."""
        p1 = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"v": 1},
            effective_from=date(2026, 1, 1),
            name="V1",
        )
        p2 = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"v": 2},
            effective_from=date(2026, 1, 1),
            name="V2",
        )
        assert not Policy.objects.filter(id=p1.id).exists()
        assert Policy.objects.filter(id=p2.id, status=Status.DRAFT).exists()


@pytest.mark.django_db
class TestPolicyResolution:
    def test_resolve_returns_highest_version(self, tenant):
        """When two published versions overlap, resolve() returns the higher version."""
        p1 = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="V1",
        )
        PolicyService.publish(p1.id)
        p2 = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": False, "penalty": 100},
            effective_from=date(2026, 1, 1),
            name="V2",
        )
        PolicyService.publish(p2.id)
        policy, answer = PolicyService.resolve(tenant, PolicyType.CANCELLATION, date(2026, 6, 1))
        assert policy.version == 2
        assert answer == {"allowed": False, "penalty": 100}

    def test_resolve_respects_effective_dates(self, tenant):
        """Policy outside effective date range is not returned."""
        p1 = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 3, 1),
            effective_to=date(2026, 6, 1),
            name="Spring",
        )
        PolicyService.publish(p1.id)
        with pytest.raises(NoPolicyFound):
            PolicyService.resolve(tenant, PolicyType.CANCELLATION, date(2026, 1, 1))

    def test_resolve_returns_exact_policy_id(self, tenant):
        """resolve() returns a Policy with an exact id for downstream pinning."""
        p = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        published = PolicyService.publish(p.id)
        resolved, _ = PolicyService.resolve(tenant, PolicyType.CANCELLATION, date(2026, 6, 1))
        assert resolved.id == published.id
        assert resolved.version == 1

    def test_resolve_no_policy_found(self, tenant):
        """No published policy matching date raises NoPolicyFound."""
        with pytest.raises(NoPolicyFound):
            PolicyService.resolve(tenant, PolicyType.CANCELLATION, date(2026, 1, 1))

    def test_can_cancel_derives_from_rules(self, tenant):
        """can_cancel() returns (allowed, penalty) from cancellation rules."""
        p = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True, "penalty_type": "nightly_rate", "penalty_value": 1},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        PolicyService.publish(p.id)
        allowed, penalty = PolicyService.can_cancel(tenant, date(2026, 6, 1))
        assert allowed is True
        assert penalty == {"penalty_type": "nightly_rate", "penalty_value": 1}


@pytest.mark.django_db
class TestTenantIsolation:
    def test_tenant_isolation(self, tenant, tenant2):
        """Each tenant sees only their own policies."""
        PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Tenant1",
        )
        PolicyService.create_draft(
            tenant=tenant2,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": False},
            effective_from=date(2026, 1, 1),
            name="Tenant2",
        )
        assert Policy.objects.filter(tenant=tenant).count() == 1
        assert Policy.objects.filter(tenant=tenant2).count() == 1


@pytest.mark.django_db
class TestEvaluationLogging:
    def test_evaluation_log_written(self, tenant):
        """resolve() creates a PolicyEvaluationLog record in the same transaction."""
        p = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Test",
        )
        PolicyService.publish(p.id)
        resolved, _ = PolicyService.resolve(tenant, PolicyType.CANCELLATION, date(2026, 6, 1))
        from apps.policies.models import PolicyEvaluationLog
        log = PolicyEvaluationLog.objects.filter(policy=resolved).first()
        assert log is not None
        assert log.context is not None
        assert log.answer == {"allowed": True}


@pytest.mark.django_db
class TestConcurrency:
    def test_concurrent_publish_same_draft(self, tenant):
        """Publishing same draft twice: first succeeds, second raises ObjectDoesNotExist."""
        from django.core.exceptions import ObjectDoesNotExist
        p = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"allowed": True},
            effective_from=date(2026, 1, 1),
            name="Concurrent",
        )
        PolicyService.publish(p.id)
        with pytest.raises(ObjectDoesNotExist):
            PolicyService.publish(p.id)

    def test_concurrent_drafts_sequential_versions(self, tenant):
        """Publishing two different drafts for same type gives sequential versions."""
        p1 = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"v": 1},
            effective_from=date(2026, 1, 1),
            name="P1",
        )
        PolicyService.publish(p1.id)
        p2 = PolicyService.create_draft(
            tenant=tenant,
            policy_type=PolicyType.CANCELLATION,
            rules={"v": 2},
            effective_from=date(2026, 1, 1),
            name="P2",
        )
        PolicyService.publish(p2.id)
        all_published = Policy.objects.filter(
            tenant=tenant, policy_type=PolicyType.CANCELLATION, status=Status.PUBLISHED
        ).order_by("version")
        assert list(all_published.values_list("version", flat=True)) == [1, 2]
