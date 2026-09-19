"""Rooms API serializers (A0). Translate/validate HTTP data only — no
business logic; ``RoomQuery``/the model fields remain the source of truth."""

from rest_framework import serializers

from apps.rooms.models import Room, RoomType


class RoomTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomType
        fields = ["id", "code", "name", "status", "max_occupancy", "attributes"]


class RoomSerializer(serializers.ModelSerializer):
    room_type = RoomTypeSerializer(read_only=True)

    class Meta:
        model = Room
        fields = [
            "id",
            "code",
            "property_id",
            "room_type",
            "operational_state",
            "current_booking_line_id",
        ]
