"""PostgreSQL RANGE partition management for ``availability_slot`` (M7, E7).

The project's first genuinely partitioned table. Django has no first-class
declarative-partitioning support (roadmap E7), so partition DDL is owned
here — shared by the initial migration (bootstraps the table + starter
partitions) and the Celery task (``apps/availability/tasks.py``) that keeps
the partition set rolling forward as the sellable horizon advances.

Monthly partitions, named ``availability_slot_yYYYYmMM``. Every function here
is a thin wrapper over raw SQL executed through a cursor/schema editor — no
ORM concept models partitioning, so there is nothing to keep "in sync" beyond
this module and the hand-written DDL in ``migrations/0001_initial.py``.
"""

from datetime import date

from django.db import connection

_TABLE = "availability_slot"
_ID_SEQUENCE = "availability_slot_id_seq"


def month_start(d: date) -> date:
    """The first day of ``d``'s month."""
    return d.replace(day=1)


def next_month_start(d: date) -> date:
    """The first day of the month AFTER ``d``'s month."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def partition_name(month: date) -> str:
    """Deterministic partition name for the month starting at ``month``."""
    return f"{_TABLE}_y{month.year:04d}m{month.month:02d}"


def iter_months(start: date, end: date):
    """Yield the first-of-month date for every month overlapping [start, end)."""
    current = month_start(start)
    stop = month_start(end)
    while current <= stop:
        yield current
        current = next_month_start(current)


def create_partition_sql(month: date) -> str:
    """DDL creating one monthly partition, idempotent (``IF NOT EXISTS``)."""
    name = partition_name(month)
    upper = next_month_start(month)
    return (
        f'CREATE TABLE IF NOT EXISTS "{name}" PARTITION OF "{_TABLE}" '
        f"FOR VALUES FROM ('{month.isoformat()}') TO ('{upper.isoformat()}');"
    )


def drop_partition_sql(month: date) -> str:
    name = partition_name(month)
    return f'DROP TABLE IF EXISTS "{name}";'


def ensure_partitions(*, start: date, end: date, cursor=None) -> list[str]:
    """Create every monthly partition covering [start, end). Idempotent.

    Returns the partition names created-or-confirmed. Used by both the
    initial migration (bootstraps the configured horizon) and the periodic
    Celery task (extends the horizon forward as "today" advances).
    """
    names = []
    owns_cursor = cursor is None
    cur = cursor or connection.cursor()
    try:
        for month in iter_months(start, end):
            cur.execute(create_partition_sql(month))
            names.append(partition_name(month))
    finally:
        if owns_cursor:
            cur.close()
    return names


def drop_partitions_before(*, cutoff: date, cursor=None) -> list[str]:
    """Drop every partition whose ENTIRE range is before ``cutoff``.

    ``availability_slot`` has no archive/audit requirement (DDS D.6: "no
    archive — drop beyond the sellable horizon, rebuildable and pointless to
    keep") — once a month's dates are fully in the past there is nothing left
    to sell there, so the partition is dropped outright rather than retained.
    Only ever touches whole partitions strictly before the cutoff month; the
    current month is never dropped even if partially elapsed.
    """
    dropped = []
    owns_cursor = cursor is None
    cur = cursor or connection.cursor()
    try:
        cur.execute(
            "SELECT c.relname FROM pg_inherits "
            "JOIN pg_class c ON c.oid = pg_inherits.inhrelid "
            "JOIN pg_class p ON p.oid = pg_inherits.inhparent "
            "WHERE p.relname = %s",
            [_TABLE],
        )
        existing = [row[0] for row in cur.fetchall()]
        cutoff_month = month_start(cutoff)
        for name in existing:
            month = _month_from_partition_name(name)
            if month is not None and month < cutoff_month:
                cur.execute(drop_partition_sql(month))
                dropped.append(name)
    finally:
        if owns_cursor:
            cur.close()
    return dropped


def _month_from_partition_name(name: str) -> date | None:
    prefix = f"{_TABLE}_y"
    if not name.startswith(prefix):
        return None
    try:
        digits = name[len(prefix) :]
        year = int(digits[0:4])
        month = int(digits[5:7])
        return date(year, month, 1)
    except (ValueError, IndexError):
        return None


def reserve_slot_ids(count: int) -> list[int]:
    """Portable surrogate-id allocation for ``availability_slot`` (see model
    docstring: ``id`` is not the composite primary key, so Django's
    auto-pk-assignment never fires for it and every write path must supply
    a value explicitly).

    PostgreSQL: a real, dedicated, concurrency-safe sequence (created in the
    initial migration) — ``nextval()`` is atomic, so concurrent allocators
    never collide. SQLite (unit tier, single-writer tests): MAX(id) + 1.
    """
    if count <= 0:
        return []
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT nextval('{_ID_SEQUENCE}') FROM generate_series(1, %s)", [count])
            return [row[0] for row in cursor.fetchall()]
    from django.db.models import Max

    from apps.availability.models import AvailabilitySlot

    current_max = AvailabilitySlot.objects.aggregate(m=Max("id"))["m"] or 0
    return list(range(current_max + 1, current_max + 1 + count))
