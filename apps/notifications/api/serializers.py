"""Notifications API serializers (A0). Read-only — M13 exposes no
staff-triggerable mutation (delivery is Celery/projector-driven)."""

from rest_framework import serializers

from apps.notifications.models import NotificationJob


class NotificationJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationJob
        fields = [
            "id",
            "notification_type",
            "channel",
            "status",
            "retry_count",
            "last_error",
            "recipient_guest_id",
            "context",
            "created_at",
        ]
