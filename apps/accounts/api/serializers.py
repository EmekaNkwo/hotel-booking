"""Serializers for the M2.3 API surface.

The HTTP ↔ domain boundary: JSON in, validated primitives out; domain
representations back to JSON. Serializers do no business logic — they
delegate to services.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import Membership, Role, UserAccount


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
