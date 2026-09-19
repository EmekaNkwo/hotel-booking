"""Reservation hold-expiry sweep (M8, roadmap: "Celery beat sweep").

The DB row (``hold_expiry_at``) is authoritative; this task is the periodic
reconciler, not a second source of truth (SDD S10.1, DDS S9 Implementation
Notes). No Redis — ``ReservationQuery.overdue_holds()`` is the entire
mechanism.
"""

from django.utils import timezone

from apps.reservations.services import ReservationQuery, ReservationService
from celery import shared_task


@shared_task(name="reservations.sweep_expired_holds")
def sweep_expired_holds() -> int:
    """Expire every overdue Held/Awaiting_Payment reservation. Safe to run
    repeatedly or concurrently — ``ReservationService.expire()`` is a no-op
    past the point a row is already settled."""
    now = timezone.now()
    overdue_ids = list(ReservationQuery.overdue_holds(now=now).values_list("id", flat=True))
    expired = 0
    for reservation_id in overdue_ids:
        ReservationService.expire(reservation_id)
        expired += 1
    return expired
