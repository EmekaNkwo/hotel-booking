"""Unit tests for the transactions discipline (M1.2 step 5).

Order: atomicity → F() expressions vs read-modify-write → conditional updates →
on_commit timing → versioning-vs-transactions.

Commit-sensitive tests use ``transaction=True`` so the test's own transaction is
the outermost one (real commits/rollbacks); everything else runs in the wrapped
transactional DB.
"""

import pytest
from django.db import connection, models, transaction
from django.db.models import F

from apps.shared.models import conditional_update


class CounterProbe(models.Model):
    """A plain counter row — deliberately NOT versioned, to show raw races."""
    count = models.PositiveIntegerField(default=0)
    owner = models.CharField(max_length=20, default="guest")

    class Meta:
        app_label = "probes"


def _ensure_table(model):
    if model._meta.db_table not in connection.introspection.table_names():
        with connection.schema_editor() as editor:
            editor.create_model(model)


@pytest.fixture(scope="module")
def counter_probe(django_db_blocker):
    with django_db_blocker.unblock():
        _ensure_table(CounterProbe)
    yield CounterProbe


@pytest.fixture(autouse=True)
def _clean_rows():
    # transaction=True tests commit for real; leave the table clean for the
    # next test. Non-transactional tests roll back anyway, so this is safe for both.
    yield
    CounterProbe.objects.all().delete()


class TestAtomicity:
    @pytest.mark.django_db(transaction=True)
    def test_atomic_rolls_back_partial_writes(self, counter_probe):
        row = counter_probe.objects.create(count=0)

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                row.count = 1
                row.save()
                raise RuntimeError("second write failed")

        # The first write did not survive — all-or-nothing held.
        assert counter_probe.objects.get(pk=row.pk).count == 0

    @pytest.mark.django_db(transaction=True)
    def test_without_atomic_a_partial_failure_persists(self, counter_probe):
        # The bug atomic exists to prevent: sequential code's default is a
        # partial commit — write #1 survives a failure at write #2.
        row = counter_probe.objects.create(count=0)

        with pytest.raises(RuntimeError):
            row.count = 1
            row.save()  # autocommit — persisted immediately
            raise RuntimeError("second write failed")

        assert counter_probe.objects.get(pk=row.pk).count == 1


class TestFExpressions:
    @pytest.mark.django_db
    def test_read_modify_write_loses_an_update(self, counter_probe):
        # Two "processes" both read the same value, both increment in Python.
        row = counter_probe.objects.create(count=0)
        process_a = counter_probe.objects.get(pk=row.pk)
        process_b = counter_probe.objects.get(pk=row.pk)

        process_a.count += 1
        process_a.save(update_fields=["count"])  # writes 1
        process_b.count += 1
        process_b.save(update_fields=["count"])  # writes 1 again

        # One increment was silently lost.
        assert counter_probe.objects.get(pk=row.pk).count == 1

    @pytest.mark.django_db
    def test_f_expression_keeps_both_increments(self, counter_probe):
        # F() is evaluated in the database — SET count = count + 1 — so both
        # increments land, even from stale readers.
        row = counter_probe.objects.create(count=0)

        counter_probe.objects.filter(pk=row.pk).update(count=F("count") + 1)
        counter_probe.objects.filter(pk=row.pk).update(count=F("count") + 1)

        assert counter_probe.objects.get(pk=row.pk).count == 2

    @pytest.mark.django_db
    def test_conditional_update_uses_f_in_the_database(self, counter_probe):
        row = counter_probe.objects.create(count=0)

        first = conditional_update(
            counter_probe.objects, {"pk": row.pk}, {"count": F("count") + 1}
        )
        second = conditional_update(
            counter_probe.objects, {"pk": row.pk}, {"count": F("count") + 1}
        )

        assert first == 1
        assert second == 1
        assert counter_probe.objects.get(pk=row.pk).count == 2


class TestConditionalUpdate:
    @pytest.mark.django_db
    def test_returns_the_number_of_rows_updated(self, counter_probe):
        row_a = counter_probe.objects.create(count=0)
        counter_probe.objects.create(count=0)

        updated = conditional_update(
            counter_probe.objects, {"count__lte": 0}, {"owner": "batch"}
        )

        assert updated == 2
        assert counter_probe.objects.get(pk=row_a.pk).owner == "batch"

    @pytest.mark.django_db
    def test_zero_rows_means_the_condition_no_longer_holds(self, counter_probe):
        # The optimistic-lock idiom: WHERE <as-read> matched nothing → lost race.
        row = counter_probe.objects.create(count=5)

        updated = conditional_update(
            counter_probe.objects, {"pk": row.pk, "count": 99}, {"count": 0}
        )

        assert updated == 0
        assert counter_probe.objects.get(pk=row.pk).count == 5

    @pytest.mark.django_db
    def test_condition_and_value_make_a_full_optimistic_lock(self, counter_probe):
        # WHERE count=0 AND SET count=1 — succeeds; the same condition as-read
        # then fails, so only one of two stale writers wins.
        row = counter_probe.objects.create(count=0)

        winner = conditional_update(
            counter_probe.objects, {"pk": row.pk, "count": 0}, {"count": 1}
        )
        loser = conditional_update(
            counter_probe.objects, {"pk": row.pk, "count": 0}, {"count": 99}
        )

        assert winner == 1
        assert loser == 0
        assert counter_probe.objects.get(pk=row.pk).count == 1


class TestOnCommit:
    @pytest.mark.django_db(transaction=True)
    def test_on_commit_fires_after_commit_not_during(self, counter_probe):
        events = []

        with transaction.atomic():
            counter_probe.objects.create(count=0)
            events.append("inside")
            transaction.on_commit(lambda: events.append("on_commit"))
        events.append("after")

        # The callback ran at commit (block exit), after the writes, before
        # the following statement — never during the transaction.
        assert events.index("inside") < events.index("on_commit")
        assert events.index("on_commit") < events.index("after")

    @pytest.mark.django_db(transaction=True)
    def test_on_commit_does_not_fire_on_rollback(self, counter_probe):
        # The race on_commit prevents: a side effect for data that never
        # committed would be a lie. On rollback the callback is discarded.
        events = []

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                counter_probe.objects.create(count=0)
                transaction.on_commit(lambda: events.append("on_commit"))
                raise RuntimeError("boom")

        assert "on_commit" not in events

    @pytest.mark.django_db(transaction=True)
    def test_on_commit_fires_in_registration_order(self, counter_probe):
        events = []

        with transaction.atomic():
            transaction.on_commit(lambda: events.append("first"))
            transaction.on_commit(lambda: events.append("second"))

        assert events == ["first", "second"]


class TestVersioningAndTransactions:
    @pytest.mark.django_db(transaction=True)
    def test_multiple_rows_move_atomically(self, counter_probe):
        # The case optimistic locking alone cannot cover: two rows that must
        # change together. Version guards protect each row; the transaction
        # makes the pair atomic.
        source = counter_probe.objects.create(count=100, owner="source")
        target = counter_probe.objects.create(count=0, owner="target")

        with transaction.atomic():
            conditional_update(
                counter_probe.objects, {"pk": source.pk, "count": 100}, {"count": 50}
            )
            conditional_update(
                counter_probe.objects, {"pk": target.pk, "count": 0}, {"count": 50}
            )

        assert counter_probe.objects.get(pk=source.pk).count == 50
        assert counter_probe.objects.get(pk=target.pk).count == 50

    @pytest.mark.django_db(transaction=True)
    def test_transfer_rolls_back_atomically(self, counter_probe):
        # A failure mid-transfer leaves both rows untouched — no money created
        # or destroyed.
        source = counter_probe.objects.create(count=100, owner="source")
        target = counter_probe.objects.create(count=0, owner="target")

        with pytest.raises(RuntimeError):
            with transaction.atomic():
                conditional_update(
                    counter_probe.objects, {"pk": source.pk, "count": 100}, {"count": 50}
                )
                conditional_update(
                    counter_probe.objects, {"pk": target.pk, "count": 0}, {"count": 50}
                )
                raise RuntimeError("ledger check failed")

        assert counter_probe.objects.get(pk=source.pk).count == 100
        assert counter_probe.objects.get(pk=target.pk).count == 0

    @pytest.mark.django_db(transaction=True)
    def test_lost_race_inside_atomic_aborts_the_whole_workflow(self, counter_probe):
        # Two transactions both believe count=0. The first wins (0 -> 1); the
        # second's conditional check finds nothing and must abort EVERYTHING it
        # already wrote in its own workflow — not just the one row.
        row = counter_probe.objects.create(count=0)

        # Transaction A wins the race.
        with transaction.atomic():
            moved = conditional_update(
                counter_probe.objects, {"pk": row.pk, "count": 0}, {"count": 1}
            )
            assert moved == 1

        # Transaction B is stale (still believes count=0). It writes a side
        # effect first, then loses the conditional check and aborts.
        with pytest.raises(ValueError):
            with transaction.atomic():
                counter_probe.objects.create(count=999, owner="b-side-effect")
                moved = conditional_update(
                    counter_probe.objects, {"pk": row.pk, "count": 0}, {"count": 1}
                )
                if not moved:
                    raise ValueError("lost the race — abort the whole workflow")

        # The loser's side effect was rolled back with the abort; the winner
        # stands.
        assert counter_probe.objects.filter(owner="b-side-effect").count() == 0
        assert counter_probe.objects.get(pk=row.pk).count == 1
