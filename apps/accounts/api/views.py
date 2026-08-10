"""DRF views for the M2.3 API surface.

The HTTP ↔ service boundary. Views are thin: parse request → serializer →
service → serialize response. Authorization is enforced by permission classes;
tenant context is established by the middleware. Business logic stays in the
service layer (SDD §14.2, DMS layer rules).

The teaching point of each view: a plain APIView makes the permission and
serialization flow fully explicit — no ViewSet magic, no annotation joins —
so a reader can trace the complete path from HTTP header to SQL in one sitting.
"""

from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasPermission, HasTenantContext
from apps.accounts.api.serializers import (
    InviteMemberSerializer,
    MembershipSerializer,
    RoleCreateSerializer,
    RoleSummarySerializer,
    UserAccountSerializer,
)
from apps.accounts.models import Membership, MembershipStatus, Role
from apps.accounts.services import AuthService, InvitationService, RoleService
from apps.tenants.models import Tenant

# ── Auth endpoints ────────────────────────────────────────────────────────


class LoginView(APIView):
    """Authenticate via email + password and establish a session cookie.

    The session is what Django's ``AuthenticationMiddleware`` (and the
    ``TenantContextMiddleware`` downstream) resolves the principal from on every
    subsequent request — so M2.3's entire tenant/RBAC chain is cookie-driven.
    """

    permission_classes = []

    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "format": "email"},
                    "password": {"type": "string"},
                },
                "required": ["email", "password"],
            }
        },
        responses={
            200: inline_serializer(
                "LoginResponse",
                fields={
                    "user": UserAccountSerializer(),
                    "memberships": MembershipSerializer(many=True),
                },
            ),
            401: {"description": "Invalid credentials"},
        },
        summary="Authenticate (session-based).",
    )
    def post(self, request: Request) -> Response:
        email = request.data.get("email", "")
        password = request.data.get("password", "")
        if not email or not password:
            return Response(
                {"detail": "email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = AuthService.authenticate(email=email, password=password)
        if user is None:
            return Response(
                {"detail": "invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        from django.contrib.auth import login

        login(request, user)

        memberships = (
            Membership.objects.for_user(user)
            .filter(status=MembershipStatus.ACTIVE)
            .prefetch_related("roles__role")
        )
        return Response(
            {
                "user": UserAccountSerializer(user).data,
                "memberships": MembershipSerializer(memberships, many=True).data,
            }
        )


class LogoutView(APIView):
    """Destroy the session cookie (SDD §14.1)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, summary="Log out (destroy session).", responses={204: None})
    def post(self, request: Request) -> Response:
        from django.contrib.auth import logout

        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Return the authenticated user, their active memberships, and the
    resolved tenant context for the current request."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Current user, memberships, and resolved tenant.",
        responses={
            200: inline_serializer(
                "MeResponse",
                fields={
                    "user": UserAccountSerializer(),
                    "memberships": MembershipSerializer(many=True),
                    "tenant_id": serializers.IntegerField(allow_null=True, required=False),
                },
            )
        },
    )
    def get(self, request: Request) -> Response:
        memberships = (
            Membership.objects.for_user(request.user)
            .filter(status=MembershipStatus.ACTIVE)
            .prefetch_related("roles__role")
        )
        return Response(
            {
                "user": UserAccountSerializer(request.user).data,
                "memberships": MembershipSerializer(memberships, many=True).data,
                "tenant_id": getattr(request, "tenant_id", None),
            }
        )


# ── Tenants (cross-tenant read — the deliberate exception) ───────────────


class TenantMembershipView(APIView):
    """List the authenticated user's tenants and their role grants (cross-tenant).

    This endpoint deliberately works WITHOUT a tenant context — it answers
    "what tenants does this user belong to?" using the user's own memberships.
    It is the one view that is intentionally not tenant-scoped.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Tenants accessible to the current user.",
        responses={
            200: inline_serializer(
                "TenantMembership",
                fields={
                    "tenant_id": serializers.IntegerField(),
                    "code": serializers.CharField(),
                    "name": serializers.CharField(),
                    "tenant_status": serializers.CharField(),
                    "membership_status": serializers.CharField(),
                    "role_names": serializers.ListField(child=serializers.CharField()),
                },
                many=True,
            )
        },
    )
    def get(self, request: Request) -> Response:
        memberships = (
            Membership.objects.for_user(request.user)
            .filter(status=MembershipStatus.ACTIVE)
            .prefetch_related("roles__role")
        )
        # ``tenant_id`` is a denormalized integer on membership (DDS A.2), not
        # an FK — fetch the tenants by id and join in Python.
        tenant_ids = [m.tenant_id for m in memberships]
        tenants = {t.pk: t for t in Tenant.objects.filter(pk__in=tenant_ids)}
        result = []
        for m in memberships:
            t = tenants[m.tenant_id]
            result.append(
                {
                    "tenant_id": m.tenant_id,
                    "code": t.code,
                    "name": t.name,
                    "tenant_status": t.status,
                    "membership_status": m.status,
                    "role_names": list(m.roles.values_list("role__name", flat=True)),
                }
            )
        return Response(result)


# ── Members (tenant-scoped) ──────────────────────────────────────────────


class MemberListView(APIView):
    """List active memberships in the current tenant (tenant-scoped).

    Requires a resolved tenant context (HasTenantContext) and the
    ``member.view`` permission.
    """

    permission_classes = [IsAuthenticated, HasTenantContext, HasPermission("member.view")]

    @extend_schema(
        summary="Active members in the current tenant.",
        responses={200: MembershipSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        memberships = (
            Membership.objects.for_tenant(request.tenant_id)
            .filter(status=MembershipStatus.ACTIVE)
            .select_related("user_account")
            .prefetch_related("roles__role")
        )
        return Response(MembershipSerializer(memberships, many=True).data)


class InviteMemberView(APIView):
    """Create an invitation in the current tenant (tenant-scoped).

    Returns the one-time raw token. Requires ``member.invite``.
    """

    permission_classes = [IsAuthenticated, HasTenantContext, HasPermission("member.invite")]

    @extend_schema(
        request=InviteMemberSerializer,
        summary="Invite a user to the current tenant.",
        responses={
            201: inline_serializer(
                "InviteResponse",
                fields={
                    "id": serializers.IntegerField(),
                    "email": serializers.EmailField(),
                    "token": serializers.CharField(),
                    "expires_at": serializers.DateTimeField(),
                },
            ),
            404: {"description": "Role not found in this tenant."},
        },
    )
    def post(self, request: Request) -> Response:
        ser = InviteMemberSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        inviter = Membership.objects.get(
            user_account=request.user,
            tenant_id=request.tenant_id,
            status=MembershipStatus.ACTIVE,
        )
        try:
            role = Role.objects.get(pk=ser.validated_data["role_id"], tenant_id=request.tenant_id)
        except Role.DoesNotExist:
            return Response(
                {"detail": "role not found in this tenant."},
                status=status.HTTP_404_NOT_FOUND,
            )

        expires_at = timezone.now() + timezone.timedelta(days=7)
        invitation, token = InvitationService.create(
            inviter=inviter,
            email=ser.validated_data["email"],
            role=role,
            expires_at=expires_at,
        )

        return Response(
            {
                "id": invitation.pk,
                "email": invitation.email,
                "token": token,
                "expires_at": invitation.expires_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )


# ── Roles (tenant-scoped, permission per action) ─────────────────────────


class RoleListView(APIView):
    """List roles in the current tenant. Requires ``role.view``."""

    permission_classes = [IsAuthenticated, HasTenantContext, HasPermission("role.view")]

    @extend_schema(
        summary="Roles in the current tenant.",
        responses={200: RoleSummarySerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        roles = Role.objects.for_tenant(request.tenant_id).prefetch_related("permissions")
        return Response(RoleSummarySerializer(roles, many=True).data)


class RoleCreateView(APIView):
    """Create a role with permission codes in the current tenant. Requires ``role.manage``."""

    permission_classes = [IsAuthenticated, HasTenantContext, HasPermission("role.manage")]

    @extend_schema(
        request=RoleCreateSerializer,
        summary="Create a role in the current tenant.",
        responses={
            201: RoleSummarySerializer,
            400: {"description": "Unknown permission code or invalid input."},
        },
    )
    def post(self, request: Request) -> Response:
        ser = RoleCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        try:
            role = RoleService.create(
                tenant_id=request.tenant_id,
                name=ser.validated_data["name"],
                permission_codes=ser.validated_data["permission_codes"],
            )
        except ValueError as exc:
            # Unknown permission code — a client error, not a server error.
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(RoleSummarySerializer(role).data, status=status.HTTP_201_CREATED)
