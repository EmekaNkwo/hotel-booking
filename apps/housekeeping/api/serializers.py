"""Housekeeping API serializers (A0)."""

from rest_framework import serializers

from apps.housekeeping.models import HousekeepingTask, InspectionResult


class HousekeepingTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = HousekeepingTask
        fields = [
            "id",
            "room_id",
            "booking_line_id",
            "business_date",
            "task_kind",
            "status",
            "assignee_id",
            "created_at",
        ]


class CheckoutSerializer(serializers.Serializer):
    booking_line_id = serializers.IntegerField()
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="")


class TaskActionSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="")


class InspectSerializer(serializers.Serializer):
    result = serializers.ChoiceField(choices=InspectionResult.choices)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="")
