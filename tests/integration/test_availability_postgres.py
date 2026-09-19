"""Postgres integration tests — the anti-oversell invariant (M7, R1, DR-05).

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_rls.py`` and ``tests/integration/test_pricing_postgres.py``.

The centerpiece is ``TestAntiOversellRace``: two REAL, independent database
connections/transactions racing for the last unit of capacity. Django opens
one connection per OS thread lazily, so two ``threading.Thread`` targets each
calling into the ORM get two genuinely separate PostgreSQL backends/sessions —
no mocking of concurrency. ``TransactionTestCase``-style behavior (via
``pytest.mark.django_db(transaction=True)``) is required so each thread's
writes actually commit to the real database instead of living inside one
uncommitted wrapper transaction the other thread could never see.
"""

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.availability.exceptions import InsufficientAvailability
from apps.availability.models import AvailabilitySlot
from apps.availability.services import AvailabilityQuery, AvailabilityService, InventoryService
from apps.properties.models import Property
from apps.rooms.models import RoomType
from apps.shared.value_objects import DateRange
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="partitioning/GiST EXCLUDE are Postgres-only"
)


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(code="acme", name="Acme Hotels", base_currency="NGN")


@pytest.fixture
def property(tenant):
    return Property.objects.create(
        tenant=tenant,
        code="TEST001",
        name="Test Hotel",
        status=Property.Status.ACTIVE,
        currency="USD",
        timezone="UTC",
        check_in_time="14:00:00",
        check_out_time="12:00:00",
    )


@pytest.fixture
def room_type(tenant):
    return RoomType.objects.create(
        tenant=tenant,
        code="STD-KING",
        name="Standard King",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
    )


@pytest.mark.django_db
class TestPartitionedTableStructure:
    def test_table_is_range_partitioned_by_business_date(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_partitioned_table pt "
                "JOIN pg_class c ON c.oid = pt.partrelid "
                "WHERE c.relname = 'availability_slot'"
            )
            assert cursor.fetchone()[0] == 1

    def test_primary_key_is_composite_including_business_date(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "JOIN pg_class c ON c.oid = i.indrelid "
                "WHERE c.relname = 'availability_slot' AND i.indisprimary "
                "ORDER BY array_position(i.indkey, a.attnum)"
            )
            columns = [row[0] for row in cursor.fetchall()]
        assert columns == ["business_date", "id"]

    def test_remaining_is_a_stored_generated_column(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT attgenerated FROM pg_attribute "
                "WHERE attrelid = 'availability_slot'::regclass AND attname = 'remaining'"
            )
            assert cursor.fetchone()[0] == "s"  # 's' = STORED generated column

    def test_check_constraints_exist(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'availability_slot'::regclass AND contype = 'c' "
                "ORDER BY conname"
            )
            names = {row[0] for row in cursor.fetchall()}
        assert {
            "availability_slot_non_negative",
            "availability_slot_valid_channel",
            "availability_slot_within_total",
        } <= names

    def test_partitions_exist_for_the_configured_horizon(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_inherits "
                "JOIN pg_class c ON c.oid = pg_inherits.inhrelid "
                "JOIN pg_class p ON p.oid = pg_inherits.inhparent "
                "WHERE p.relname = 'availability_slot'"
            )
            assert cursor.fetchone()[0] > 0

    def test_gist_exclude_constraints_exist_on_inventory_block_and_channel_allocation(self):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT conname FROM pg_constraint WHERE contype = 'x' "
                "AND conname IN ("
                "'inventory_block_no_overlap_per_room_type', "
                "'channel_allocation_no_overlap_per_room_type')"
            )
            names = {row[0] for row in cursor.fetchall()}
        assert names == {
            "inventory_block_no_overlap_per_room_type",
            "channel_allocation_no_overlap_per_room_type",
        }


class TestAntiOversellRace:
    """The M7 centerpiece: two real connections, one unit of capacity."""

    @pytest.mark.django_db(transaction=True)
    def test_exactly_one_of_two_concurrent_sellers_wins_the_last_unit(self):
        tenant = Tenant.objects.create(code="race1", name="Race Hotels", base_currency="NGN")
        property_ = Property.objects.create(
            tenant=tenant,
            code="RACE1",
            name="Race Hotel",
            status=Property.Status.ACTIVE,
            currency="USD",
            timezone="UTC",
            check_in_time="14:00:00",
            check_out_time="12:00:00",
        )
        room_type = RoomType.objects.create(
            tenant=tenant,
            code="RACE-KING",
            name="Race King",
            status=RoomType.Status.ACTIVE,
            max_occupancy=2,
        )
        today = timezone.now().date()
        # A 3-night window with exactly ONE sellable unit per night — proves
        # "no partial multi-night consumption" alongside the single-unit race.
        AvailabilityService.initialize_horizon(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
            total_units=1,
            start_date=today,
            horizon_days=3,
        )
        date_range = DateRange(today, today + timedelta(days=3))

        results: dict[str, tuple[dict | None, Exception | None]] = {}
        barrier = threading.Barrier(2)

        def _attempt(caller: str, idempotency_key: str) -> None:
            try:
                barrier.wait(timeout=10)  # start both threads at the same instant
                response = InventoryService.sell(
                    tenant_id=tenant.id,
                    property_id=property_.id,
                    room_type_id=room_type.id,
                    date_range=date_range,
                    quantity=1,
                    idempotency_key=idempotency_key,
                )
                results[caller] = (response, None)
            except Exception as exc:  # noqa: BLE001 — captured for the assertion, not swallowed
                results[caller] = (None, exc)
            finally:
                connection.close()  # each thread owns its own connection

        thread_a = threading.Thread(target=_attempt, args=("A", "race-key-A"))
        thread_b = threading.Thread(target=_attempt, args=("B", "race-key-B"))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=15)
        thread_b.join(timeout=15)

        assert set(results) == {"A", "B"}
        successes = [c for c, (resp, exc) in results.items() if exc is None]
        failures = [(c, exc) for c, (resp, exc) in results.items() if exc is not None]
        assert len(successes) == 1, f"expected exactly one winner, got {results!r}"
        assert len(failures) == 1, f"expected exactly one loser, got {results!r}"
        loser, loser_exc = failures[0]
        assert isinstance(loser_exc, InsufficientAvailability), (
            f"loser must fail with InsufficientAvailability, got {loser_exc!r}"
        )

        # Final state: exactly one unit sold, on EVERY night — no negative
        # remaining, no partial multi-night consumption.
        remaining = AvailabilityQuery.remaining_for_range(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
            date_range=date_range,
        )
        assert list(remaining.values()) == [0, 0, 0]
        assert all(r >= 0 for r in remaining.values())
        rows = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
        ).order_by("business_date")
        assert [row.sold for row in rows] == [1, 1, 1]  # never [1,1,0] or similar partial state

        # The losing caller retries with the SAME idempotency key — since no
        # idempotency record survived the loser's rolled-back transaction
        # (IdempotencyService only persists on success), this re-runs the
        # guarded check fresh. With capacity still fully consumed, it must
        # raise again — never silently succeed and double-consume.
        loser_key = "race-key-A" if loser == "A" else "race-key-B"
        with pytest.raises(InsufficientAvailability):
            InventoryService.sell(
                tenant_id=tenant.id,
                property_id=property_.id,
                room_type_id=room_type.id,
                date_range=date_range,
                quantity=1,
                idempotency_key=loser_key,
            )
        rows_after_retry = AvailabilitySlot.objects.filter(
            tenant_id=tenant.id,
            property_id=property_.id,
            room_type_id=room_type.id,
        ).order_by("business_date")
        assert [row.sold for row in rows_after_retry] == [1, 1, 1]  # unchanged
