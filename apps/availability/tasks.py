"""Partition management Celery task (M7, E7 roadmap task).

Keeps the ``availability_slot`` partition set rolling forward as "today"
advances: ensures every month through the configured horizon has a
partition, and drops partitions that have fallen entirely into the past
(DDS D.6: "no archive — drop beyond the sellable horizon, rebuildable and
pointless to keep"). PostgreSQL-only — a no-op on SQLite, where the table
isn't partitioned at all.

Registered as ``autodiscover_tasks()`` picks up ``apps.availability.tasks``
automatically (``config/celery.py``); wire the beat schedule (periodic
invocation, e.g. daily) in ``config/settings/base.py``'s
``CELERY_BEAT_SCHEDULE`` once a real deployment needs it.
"""

from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.availability import partitioning
from celery import shared_task


@shared_task(name="availability.manage_partitions")
def manage_availability_partitions(horizon_days: int | None = None) -> dict:
    """Ensure partitions exist through the horizon; drop ones fully in the past."""
    if connection.vendor != "postgresql":
        return {"vendor": connection.vendor, "created": [], "dropped": []}

    today = timezone.now().date()
    horizon = horizon_days if horizon_days is not None else settings.AVAILABILITY_HORIZON_DAYS
    created = partitioning.ensure_partitions(start=today, end=today + timedelta(days=horizon))
    dropped = partitioning.drop_partitions_before(cutoff=today)
    return {"vendor": "postgresql", "created": created, "dropped": dropped}
