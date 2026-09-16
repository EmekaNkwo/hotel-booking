"""Postgres integration tests — RateOverride GiST EXCLUDE (M6, DDS S8/A.9).

The unit tier runs on SQLite, where ``EXCLUDE USING gist`` does not exist —
non-overlap there is guaranteed by ``PricingService.add_override()``'s
inclusive-range application-layer check (see
``tests/unit/pricing/test_pricing_lifecycle.py::TestRateOverride``). This
tier proves the Postgres-only DB-level backstop itself, applied by
``apps/pricing/migrations/0002_exclude_rate_override_overlap.py``: creating
rows directly via the ORM, bypassing ``PricingService``, so only the
database's own constraint can catch an overlap.

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_rls.py`` and ``tests/integration/test_guests_postgres.py``.
"""

from datetime import date

import pytest
from django.db import IntegrityError, connection

from apps.pricing.models import AdjustmentType, RateOverride, RatePlan, RatePlanStatus
from apps.properties.models import Property
from apps.rooms.models import RoomType
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="EXCLUDE USING gist is Postgres-only"
)


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(code="acme", name="Acme Hotels", base_currency="NGN")


@pytest.fixture
def property(tenant):
    return Property.objects.create(
        tenant=tenant, code="TEST001", name="Test Hotel", status=Property.Status.ACTIVE,
        currency="USD", timezone="UTC", check_in_time="14:00:00", check_out_time="12:00:00",
    )


@pytest.fixture
def room_type(tenant):
    return RoomType.objects.create(
        tenant=tenant, code="STD-KING", name="Standard King",
        status=RoomType.Status.ACTIVE, max_occupancy=2,
    )


@pytest.fixture
def rate_plan(tenant, property, room_type):
    return RatePlan.objects.create(
        tenant=tenant, property=property, room_type=room_type, code="STD-RACK",
        base_rate_minor_units=10000, currency=property.currency, status=RatePlanStatus.ACTIVE,
    )


@pytest.mark.django_db
class TestExcludeConstraintExists:
    def test_exclude_constraint_is_registered(self, rate_plan):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conname = 'rate_override_no_overlap' AND contype = 'x'"
            )
            row = cursor.fetchone()
        assert row is not None


@pytest.mark.django_db
class TestExcludeConstraintEnforcement:
    def test_overlapping_inclusive_range_rejected_at_db_level(self, tenant, rate_plan):
        RateOverride.objects.create(
            tenant=tenant, rate_plan=rate_plan,
            start_date=date(2026, 12, 20), end_date=date(2026, 12, 26),
            adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=10,
        )

        with pytest.raises(IntegrityError):
            # Shares Dec 26 with the existing [20, 26] range — the ORM never
            # validates this; only the DB constraint can catch it here.
            RateOverride.objects.create(
                tenant=tenant, rate_plan=rate_plan,
                start_date=date(2026, 12, 26), end_date=date(2026, 12, 31),
                adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=10,
            )

    def test_adjacent_non_overlapping_range_is_accepted_at_db_level(self, tenant, rate_plan):
        RateOverride.objects.create(
            tenant=tenant, rate_plan=rate_plan,
            start_date=date(2026, 12, 20), end_date=date(2026, 12, 25),
            adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=10,
        )

        # Dec 26 is the day after Dec 25 — no shared day under inclusive semantics.
        second = RateOverride.objects.create(
            tenant=tenant, rate_plan=rate_plan,
            start_date=date(2026, 12, 26), end_date=date(2026, 12, 31),
            adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=10,
        )
        assert second.start_date == date(2026, 12, 26)

    def test_inactive_overrides_are_excluded_from_the_constraint(self, tenant, rate_plan):
        first = RateOverride.objects.create(
            tenant=tenant, rate_plan=rate_plan,
            start_date=date(2026, 12, 20), end_date=date(2026, 12, 26),
            adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=10, active=False,
        )
        assert first.active is False

        # Same range, but the prior row is inactive — the constraint's
        # `condition=Q(active=True)` means it never conflicts.
        second = RateOverride.objects.create(
            tenant=tenant, rate_plan=rate_plan,
            start_date=date(2026, 12, 20), end_date=date(2026, 12, 26),
            adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=15, active=True,
        )
        assert second.active is True

    def test_overlap_across_different_rate_plans_is_allowed(self, tenant, property, room_type):
        """The EXCLUDE is scoped per rate_plan (rate_plan WITH =) — two
        different plans may have overrides on the same calendar dates."""
        plan_a = RatePlan.objects.create(
            tenant=tenant, property=property, room_type=room_type, code="PLAN-A",
            base_rate_minor_units=10000, currency=property.currency,
            status=RatePlanStatus.ACTIVE,
        )
        plan_b = RatePlan.objects.create(
            tenant=tenant, property=property, room_type=room_type, code="PLAN-B",
            base_rate_minor_units=12000, currency=property.currency,
            status=RatePlanStatus.ACTIVE,
        )

        RateOverride.objects.create(
            tenant=tenant, rate_plan=plan_a,
            start_date=date(2026, 12, 20), end_date=date(2026, 12, 26),
            adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=10,
        )
        # Identical date range, different plan — must succeed.
        second = RateOverride.objects.create(
            tenant=tenant, rate_plan=plan_b,
            start_date=date(2026, 12, 20), end_date=date(2026, 12, 26),
            adjustment_type=AdjustmentType.PERCENT, adjustment_minor_units=10,
        )
        assert second.rate_plan_id == plan_b.id
