"""Guests API serializers (A0)."""

from rest_framework import serializers

from apps.guests.models import GuestProfile


class GuestProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuestProfile
        fields = [
            "id",
            "primary_email",
            "primary_phone",
            "name",
            "language",
            "status",
            "created_at",
        ]


class GuestCreateSerializer(serializers.Serializer):
    """Input for ``GuestService.resolve()`` — find-or-create by identity.
    Structural validation only; ``Email``/``PhoneNumber``/``GuestName``
    value-object validation happens inside the service, unchanged."""

    email = serializers.EmailField(required=False, allow_null=True, default=None)
    phone = serializers.CharField(required=False, allow_null=True, allow_blank=True, default=None)
    given_name = serializers.CharField(required=False, allow_blank=True, default="")
    family_name = serializers.CharField(required=False, allow_blank=True, default="")
    language = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError("email or phone is required.")
        return attrs
