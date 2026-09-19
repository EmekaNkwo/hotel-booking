"""Reservations API serializers (A0)."""

from rest_framework import serializers

from apps.reservations.models import Reservation, ReservationLine


class ReservationLineInputSerializer(serializers.Serializer):
    room_type_id = serializers.IntegerField()
    arrival_date = serializers.DateField()
    departure_date = serializers.DateField()
    adults = serializers.IntegerField(min_value=1, default=1)
    children = serializers.IntegerField(min_value=0, default=0)
    quantity = serializers.IntegerField(min_value=1, default=1)


class ReservationCreateSerializer(serializers.Serializer):
    property_id = serializers.IntegerField()
    guest_email = serializers.EmailField(required=False, allow_null=True, default=None)
    guest_phone = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, default=None
    )
    lines = ReservationLineInputSerializer(many=True)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("at least one line is required.")
        return value


class ReservationLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReservationLine
        fields = [
            "id",
            "line_no",
            "room_type_id",
            "arrival_date",
            "departure_date",
            "quantity",
            "price_snapshot",
        ]


class ReservationSerializer(serializers.ModelSerializer):
    lines = ReservationLineSerializer(many=True, read_only=True)

    class Meta:
        model = Reservation
        fields = [
            "id",
            "reservation_ref",
            "status",
            "channel",
            "hold_expiry_at",
            "price_snapshot",
            "policy_snapshot",
            "guest_profile_id",
            "property_id",
            "lines",
            "created_at",
        ]


class IdempotencyKeyInputSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(required=False, allow_blank=True, default="")
