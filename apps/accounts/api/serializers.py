"""Serializers for the M2.3 API surface.

The HTTP ↔ domain boundary: JSON in, validated primitives out; domain
representations back to JSON. Serializers do no business logic — they
delegate to services.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import Membership, MfaDevice, MfaDeviceType, Role, UserAccount


class UserAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAccount
        fields = ["id", "email", "is_staff", "is_active"]
        read_only_fields = fields


class RoleSummarySerializer(serializers.ModelSerializer):
    """A role with its permission codes (read-only)."""

    permission_codes = serializers.SlugRelatedField(
        slug_field="permission_code",
        many=True,
        read_only=True,
        source="permissions",
    )

    class Meta:
        model = Role
        fields = ["id", "name", "status", "permission_codes"]
        read_only_fields = fields


class RoleCreateSerializer(serializers.Serializer):
    """The write shape: name + permission codes (validated against the registry)."""

    name = serializers.CharField(max_length=60)
    permission_codes = serializers.ListField(
        child=serializers.CharField(max_length=80),
        min_length=1,
    )


class MembershipSerializer(serializers.ModelSerializer):
    email = serializers.CharField(source="user_account.email", read_only=True)
    role_names = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "tenant_id", "email", "status", "role_names"]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_role_names(self, obj):
        return list(obj.roles.values_list("role__name", flat=True))


class InviteMemberSerializer(serializers.Serializer):
    """The write shape for the invite endpoint."""

    email = serializers.EmailField()
    role_id = serializers.IntegerField()


class MfaDeviceSerializer(serializers.ModelSerializer):
    """Read-only device summary (M2.5 step 5).

    Deliberately omits ``secret_key`` — the stored Fernet ciphertext — and any
    plaintext TOTP secret. The only plaintext exposure is the one-shot
    provisioning URI returned by enrollment (service contract); every other
    endpoint never sees it.
    """

    verified = serializers.SerializerMethodField()
    removed = serializers.SerializerMethodField()

    class Meta:
        model = MfaDevice
        fields = ["id", "device_type", "name", "verified", "removed", "created_at"]
        read_only_fields = fields

    def get_verified(self, obj) -> bool:
        return obj.verified_at is not None

    def get_removed(self, obj) -> bool:
        return obj.removed_at is not None


class MfaEnrollRequestSerializer(serializers.Serializer):
    """Enrollment input: a device name, optionally an explicit device type.

    ``device_type`` exposes the schema's closed set (totp/webauthn); only totp
    is implemented at M2.5, so webauthn is rejected by the service (400).
    """

    name = serializers.CharField(max_length=80)
    device_type = serializers.ChoiceField(
        choices=MfaDeviceType.choices,
        default=MfaDeviceType.TOTP,
        required=False,
    )


class MfaEnrollResponseSerializer(serializers.Serializer):
    """The one-shot enrollment result: the device plus its provisioning URI.

    The URI embeds the plaintext TOTP secret for the user to scan; it is
    returned exactly once and never persisted (DDS §1).
    """

    device = MfaDeviceSerializer()
    provisioning_uri = serializers.CharField()


class MfaVerifyRequestSerializer(serializers.Serializer):
    """The TOTP code the user reads from their authenticator app."""

    code = serializers.CharField(min_length=6, max_length=8)
