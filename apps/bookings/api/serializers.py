"""Bookings API serializers (A0)."""

from rest_framework import serializers

from apps.bookings.models import Booking, BookingLine


class BookingLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingLine
        fields = [
            "id",
            "line_no",
            "room_type_id",
            "room_id",
            "arrival_date",
            "departure_date",
            "status",
            "price_snapshot",
        ]


class BookingSerializer(serializers.ModelSerializer):
    lines = BookingLineSerializer(many=True, read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "booking_ref",
            "aggregate_status",
            "currency",
            "total_minor_units",
            "arrival_date",
            "departure_date",
            "guest_profile_id",
            "reservation_id",
            "guest_snapshot",
            "lines",
            "created_at",
        ]


class BookingConfirmSerializer(serializers.Serializer):
    reservation_id = serializers.IntegerField()
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="")
