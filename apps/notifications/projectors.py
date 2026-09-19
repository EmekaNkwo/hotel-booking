"""NotificationProjector — the event-to-job consumer (M13).

Structurally identical to ``RoomStateProjector`` (M7): filters
``DomainEvent`` by the notifiable event types, checkpoints via
``ProjectionState``, and folds each event into (at most) one
``NotificationJob`` per channel. The ``UniqueConstraint(source_event,
channel)`` is the DB-level backstop against ever creating two jobs for the
same event+channel, even if this projector's own checkpoint were re-run.
"""

from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.notifications.models import (
    ChannelPreference,
    NotificationJob,
    NotificationTemplate,
    TemplateStatus,
)
from apps.notifications.resolvers import NOTIFIABLE_EVENT_TYPES, NotificationRecipientResolver
from apps.shared.models import DomainEvent, ProjectionState, ProjectionStatus

PROJECTION_NAME = "notifications.dispatch"
CHANNELS = ("email",)
DEFAULT_LOCALE = "en"


def _notification_type_for(event_type: str) -> str:
    return event_type.replace(".", "_")


class NotificationProjector:
    """Folds notifiable ``DomainEvent`` rows into ``NotificationJob`` rows."""

    @classmethod
    def process_batch(cls, *, batch_size: int = 100) -> int:
        state, _ = ProjectionState.objects.get_or_create(
            projection_name=PROJECTION_NAME, defaults={"status": ProjectionStatus.ACTIVE}
        )
        processed = 0
        for event in cls._pending_events(state, batch_size):
            try:
                with transaction.atomic():
                    cls._apply(event)
                    state.last_event_id = cls._checkpoint(event)
                    state.last_processed_at = timezone.now()
                    state.status = ProjectionStatus.ACTIVE
                    state.last_error = ""
                    state.save(
                        update_fields=[
                            "last_event_id",
                            "last_processed_at",
                            "status",
                            "last_error",
                            "updated_at",
                        ]
                    )
            except Exception as exc:  # noqa: BLE001 — surface, never silently drop an event
                state.status = ProjectionStatus.FAILED
                state.last_error = str(exc)[:500]
                state.save(update_fields=["status", "last_error", "updated_at"])
                break
            processed += 1
        return processed

    @staticmethod
    def _checkpoint(event: DomainEvent) -> str:
        return f"{event.occurred_at.isoformat()}|{event.pk}"

    @staticmethod
    def _pending_events(state: ProjectionState, batch_size: int):
        qs = DomainEvent.objects.filter(event_type__in=NOTIFIABLE_EVENT_TYPES).order_by(
            "occurred_at", "id"
        )
        if state.last_event_id:
            occurred_at_str, _, pk_str = state.last_event_id.partition("|")
            occurred_at = datetime.fromisoformat(occurred_at_str)
            checkpoint_pk = int(pk_str)
            qs = qs.filter(
                Q(occurred_at__gt=occurred_at)
                | (Q(occurred_at=occurred_at) & Q(id__gt=checkpoint_pk))
            )
        return list(qs[:batch_size])

    @classmethod
    def _apply(cls, event: DomainEvent) -> None:
        resolved = NotificationRecipientResolver.resolve(event)
        if resolved is None:
            return  # no resolvable guest recipient — nothing to notify

        notification_type = _notification_type_for(event.event_type)
        for channel in CHANNELS:
            if ChannelPreference.objects.filter(
                tenant_id=resolved.tenant_id,
                guest_profile_id=resolved.guest_profile_id,
                channel=channel,
                suppressed=True,
            ).exists():
                continue  # suppressed — no job, no trace of an unsent message

            template = NotificationTemplate.objects.filter(
                tenant_id=resolved.tenant_id,
                notification_type=notification_type,
                channel=channel,
                locale=DEFAULT_LOCALE,
                status=TemplateStatus.PUBLISHED,
            ).first()

            try:
                with transaction.atomic():
                    NotificationJob.objects.create(
                        tenant_id=resolved.tenant_id,
                        source_event=event,
                        recipient_guest_id=resolved.guest_profile_id,
                        notification_type=notification_type,
                        channel=channel,
                        template=template,
                        context=resolved.context,
                    )
            except IntegrityError:
                # UniqueConstraint(source_event, channel) — a job already
                # exists for this event+channel (replay/duplicate batch).
                pass
