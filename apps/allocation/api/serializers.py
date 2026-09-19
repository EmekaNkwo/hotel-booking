"""Allocation API serializers (A0)."""

from rest_framework import serializers

from apps.allocation.models import AllocationRecord


class AllocationRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllocationRecord
        fields = [
            "id",
            "booking_line_id",
            "room_id",
            "override",
            "override_reason",
            "criteria",
            "scores",
            "reason",
            "created_at",
        ]


class AllocateLineSerializer(serializers.Serializer):
    booking_line_id = serializers.IntegerField()
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="")
