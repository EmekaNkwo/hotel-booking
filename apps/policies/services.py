"""Policy Engine — M4 policy-as-data foundation.

Policy is versioned, tenant-configurable data evaluated via PolicyService.
Services ask, never embed rules.

Authoritative references:
- SDD §11.7 — Policy Engine
- DDS §21 — Policy Engine
- Implementation roadmap M4
"""

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.policies.models import Policy, PolicyEvaluationLog, PolicyType


class NoPolicyFound(Exception):
    """Raised when no published policy matches the given date."""


class InvalidStateTransition(Exception):
    """Raised when an invalid lifecycle transition is attempted."""


class PolicyService:
    """Service-layer policy resolution — orchestrates, never embeds."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def create_draft(
        tenant,
        policy_type: PolicyType,
        rules: dict,
        effective_from,
        effective_to=None,
        property_id=None,
        name: str = None,
        description: str = None,
        created_by=None,
    ) -> Policy:
        """Create a draft policy (mutable). One draft per (tenant, policy_type)."""
        # Enforce single draft per (tenant, type)
        Policy.objects.filter(
            tenant=tenant, policy_type=policy_type, version__isnull=True
        ).delete()

        policy = Policy(
            tenant=tenant,
            policy_type=policy_type,
            version=None,
            status="draft",
            effective_from=effective_from,
            effective_to=effective_to,
            rules=rules,
            property_id=property_id,
            name=name,
            description=description,
            created_by=created_by,
        )
        policy.full_clean()
        policy.save(using="default")
        return policy

    @staticmethod
    def update_draft(policy_id: int, **updates) -> Policy:
        """Update a draft policy's rules or effective dates."""
        policy = Policy.objects.get(id=policy_id, status="draft")
        for field, value in updates.items():
            setattr(policy, field, value)
        policy.full_clean()
        policy.save(using="default")
        return policy

    @staticmethod
    def publish(policy_id: int, actor=None) -> Policy:
        """Publish a draft policy — creates immutable published version.

        Assigns the next sequential version number. The draft is discarded.
        Concurrent publishes of the same draft are serialized via
        select_for_update(); the second caller receives ObjectDoesNotExist.
        """
        # First, check the policy exists and is in draft state — raise
        # InvalidStateTransition if it is not (avoids leaking DoesNotExist).
        try:
            current = Policy.objects.get(id=policy_id)
        except Policy.DoesNotExist:
            raise
        if current.status != "draft":
            raise InvalidStateTransition(
                f"Cannot publish policy in status {current.status!r}; "
                "only draft policies can be published."
            )

        with transaction.atomic():
            draft = (
                Policy.objects.select_for_update()
                .get(id=policy_id, status="draft")
            )

            # Determine next version
            max_version = (
                Policy.objects.filter(
                    tenant=draft.tenant,
                    policy_type=draft.policy_type,
                    version__gt=0,
                )
                .aggregate(max_version=Max("version"))
                .get("max_version")
                or 0
            )
            next_version = max_version + 1

            # Create immutable published row
            Policy.objects.create(
                tenant=draft.tenant,
                policy_type=draft.policy_type,
                version=next_version,
                status="published",
                effective_from=draft.effective_from,
                effective_to=draft.effective_to,
                rules=draft.rules,
                property_id=draft.property_id,
                name=draft.name,
                description=draft.description,
                published_at=timezone.now(),
                created_by=draft.created_by,
            )

            # Discard the draft
            draft.delete()

            return Policy.objects.get(
                tenant=draft.tenant,
                policy_type=draft.policy_type,
                version=next_version,
            )

    @staticmethod
    def retire(policy_id: int, actor=None) -> Policy:
        """Retire a published policy — sets status=RETIRED only.

        Historical content is never rewritten. Only lifecycle fields may change.
        """
        try:
            current = Policy.objects.get(id=policy_id)
        except Policy.DoesNotExist:
            raise
        if current.status != "published":
            raise InvalidStateTransition(
                f"Cannot retire policy in status {current.status!r}; "
                "only published policies can be retired."
            )

        with transaction.atomic():
            policy = Policy.objects.get(id=policy_id, status="published")
            policy.status = "retired"
            # Optional: set effective_to to today if not already set
            if policy.effective_to is None:
                policy.effective_to = timezone.now().date()
            policy.save(using="default")
            return policy

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @staticmethod
    def resolve(
        tenant,
        policy_type: PolicyType,
        context_date,
        property_id=None,
    ) -> tuple:
        """Resolve the effective published policy for the given date.

        Returns (policy: Policy, answer: dict).
        Raises NoPolicyFound when no published version matches.
        Writes PolicyEvaluationLog synchronously in the same transaction.
        """
        # Build base query — published versions whose effective_from <= context_date
        matching = Policy.objects.filter(
            tenant=tenant,
            policy_type=policy_type,
            status="published",
            effective_from__lte=context_date,
        )

        # Apply property scope: either matching property_id or no property
        if property_id is not None:
            matching = matching.filter(
                Q(property_id=property_id) | Q(property__isnull=True)
            )

        # Exclude those whose effective_to is already past (effective_to > context_date)
        # effective_to NULL means open-ended (no expiry)
        matching = matching.filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=context_date)
        )

        # Order by version descending — highest version wins
        matching = matching.order_by("-version")

        try:
            policy = matching[0]
        except IndexError as err:
            raise NoPolicyFound(
                f"No published policy found for tenant {tenant}, "
                f"policy_type {policy_type}, date {context_date}"
            ) from err

        # Build answer from rules
        answer = policy.rules if policy.rules else {}

        # Write evaluation log synchronously with proper composite primary key
        # id is required as part of the composite primary key (evaluated_at, id)
        PolicyEvaluationLog.objects.create(
            evaluated_at=timezone.now(),
            id=int(1000000 + policy.id),  # Use policy ID as part of id to ensure uniqueness
            tenant=tenant,
            policy=policy,
            context={"date": str(context_date), "property_id": str(property_id)},
            answer=answer,
        )

        return policy, answer

    # ------------------------------------------------------------------
    # Convenience question methods
    # ------------------------------------------------------------------

    @staticmethod
    def can_cancel(
        tenant, context_date, property_id=None
    ) -> tuple[bool, dict | None]:
        """(allowed: bool, penalty: dict | None)

        Delegates to resolve() and formats the answer.
        """
        policy, answer = PolicyService.resolve(
            tenant, PolicyType.CANCELLATION, context_date, property_id
        )
        allowed = answer.get("allowed", False)
        # Build penalty dict from penalty_type/penalty_value keys in rules
        penalty = {}
        if "penalty_type" in answer:
            penalty["penalty_type"] = answer["penalty_type"]
        if "penalty_value" in answer:
            penalty["penalty_value"] = answer["penalty_value"]
        if not penalty:
            penalty = None
        return allowed, penalty

    @staticmethod
    def refund_rule(tenant, context_date, property_id=None) -> dict | None:
        """Returns refund rule dict or None if no policy matches."""
        _, answer = PolicyService.resolve(
            tenant, PolicyType.REFUND, context_date, property_id
        )
        return answer if answer else None

    @staticmethod
    def deposit_required(tenant, context_date, property_id=None) -> tuple:
        """(required: bool, amount: dict | None)"""
        policy, answer = PolicyService.resolve(
            tenant, PolicyType.DEPOSIT, context_date, property_id
        )
        required = answer.get("required", False)
        amount = answer.get("amount", None)
        return required, amount

    @staticmethod
    def check_in_time(tenant, property_id=None) -> dict:
        """Returns check-in time window and grace minutes."""
        from datetime import date as date_type
        policy, answer = PolicyService.resolve(
            tenant, PolicyType.CHECK_IN, date_type.today(), property_id
        )
        return answer if answer else {"earliest": "15:00", "latest": "23:00", "grace_minutes": 30}

    @staticmethod
    def check_out_time(tenant, property_id=None) -> dict:
        """Returns latest check-out time and late fee."""
        from datetime import date as date_type
        policy, answer = PolicyService.resolve(
            tenant, PolicyType.CHECK_OUT, date_type.today(), property_id
        )
        return answer if answer else {
            "latest": "12:00",
            "late_fee_per_hour": None,
        }

    @staticmethod
    def cleaning_standard(tenant, room_type_id=None, property_id=None) -> dict | None:
        """Returns cleaning standard dict or None."""
        from datetime import date as date_type
        policy, answer = PolicyService.resolve(
            tenant,
            PolicyType.CLEANING,
            date_type.today(),  # no date needed for cleaning
            property_id,
        )
        return answer if answer else None

    @staticmethod
    def pricing_policy(tenant, context_date, property_id=None) -> dict | None:
        """Returns pricing policy rules or None."""
        _, answer = PolicyService.resolve(
            tenant, PolicyType.PRICING, context_date, property_id
        )
        return answer if answer else None