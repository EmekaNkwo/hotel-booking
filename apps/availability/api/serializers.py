"""Availability API serializers (A0)."""

from rest_framework import serializers


class AvailabilitySearchSerializer(serializers.Serializer):
    """Query params for the availability+pricing composite search."""

    property_id = serializers.IntegerField()
    room_type_id = serializers.IntegerField()
    start = serializers.DateField()
    end = serializers.DateField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    adults = serializers.IntegerField(min_value=1, default=1)
    children = serializers.IntegerField(min_value=0, default=0)
