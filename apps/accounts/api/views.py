"""DRF views for the M2.3 API surface.

The HTTP ↔ service boundary. Views are thin: parse request → serializer →
service → serialize response. Authorization is enforced by permission classes;
tenant context is established by the middleware. Business logic stays in the
service layer (SDD §14.2, DMS layer rules).

The teaching point of each view: a plain APIView makes the permission and
serialization flow fully explicit — no ViewSet magic, no annotation joins —
so a reader can trace the complete path from HTTP header to SQL in one sitting.
"""

from django.conf import settings
from django.contrib.auth import login
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
    MfaDeviceSerializer,
    MfaEnrollRequestSerializer,
    MfaEnrollResponseSerializer,
    MfaVerifyRequestSerializer,
    RoleCreateSerializer,
    RoleSummarySerializer,
    UserAccountSerializer,
)
from apps.accounts.api.throttles import AuthLoginThrottle, AuthMfaThrottle
from apps.accounts.exceptions import (
    LastOwnerSelfRevoke,
    MembershipNotActive,
    MfaDeviceNotFound,
    MfaDeviceRemoved,
    MfaDeviceUnverified,
    MfaDuplicateDevice,
    MfaError,
    MfaInvalidCode,
    MfaLastDevice,
)
from apps.accounts.models import (
    Membership,
    MembershipStatus,
    MfaDevice,
    Role,
    UserAccount,
)
from apps.accounts.services import (
    AuthService,
    InvitationService,
    MembershipService,
    MfaService,
    RoleService,
)
from apps.tenants.models import Tenant

# ── Auth endpoints ────────────────────────────────────────────────────────


class LoginView(APIView):
    """Authenticate via email + password and establish a session cookie.

    The session is what Django's ``AuthenticationMiddleware`` (and the
    ``TenantContextMiddleware`` downstream) resolves the principal from on every
    subsequent request — so M2.3's entire tenant/RBAC chain is cookie-driven.
    """

    permission_classes = []
    throttle_classes = [AuthLoginThrottle]

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

        if MfaService.requires_challenge(user=user):
            # Two-step login (SDD §14.1): the password is verified but the
            # session is NOT authenticated yet. Flush first so any pre-existing
            # authenticated session or stale pending state is discarded (clean
            # slate + a fresh session id — fixation-safe), then bind a short-
            # lived challenge to this session. The challenge travels in the
            # session cookie, so it is bound to this client and cannot be used
            # by another user.
            request.session.flush()
            request.session["mfa_pending"] = {
                "user_id": user.pk,
                "expires_at": (
                    timezone.now()
                    + timezone.timedelta(seconds=settings.MFA_PENDING_TIMEOUT_SECONDS)
                ).isoformat(),
            }
            return Response(
                {"requires_mfa": True, "expires_in": settings.MFA_PENDING_TIMEOUT_SECONDS},
                status=status.HTTP_202_ACCEPTED,
            )

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


def _consume_challenge(request: Request) -> UserAccount | None:
    """Validate the session's pending MFA challenge; return its user or None.

    Fails closed: a malformed, expired, or user-gone challenge returns None
    AFTER flushing the session — the challenge is discarded and can never be
    replayed. The caller 401s on None with one opaque message (no oracle to
    distinguish which invalid state occurred).
    """
    pending = request.session.get("mfa_pending")
    if not isinstance(pending, dict):
        request.session.flush()
        return None
    try:
        user_id = int(pending["user_id"])
        expires_at = timezone.datetime.fromisoformat(pending["expires_at"])
    except (KeyError, TypeError, ValueError):
        request.session.flush()
        return None
    if timezone.now() > expires_at:
        request.session.flush()
        return None
    user = UserAccount.objects.filter(pk=user_id).first()
    if user is None:
        request.session.flush()
        return None
    return user


class MfaLoginView(APIView):
    """Complete the two-step login with a TOTP code (second factor).

    The pending challenge lives in this session (created by the password step)
    and is bound to the user it was issued for. Success FLUSHES the session
    before ``login()`` — the pending state is consumed (no replay) and the
    authenticated session gets a brand-new id (no fixation). Failure never
    authenticates; an expired, malformed, or already-consumed challenge fails
    closed and is discarded. The code is verified through ``MfaService.
    verify_code`` — no TOTP logic lives here.
    """

    permission_classes = []
    throttle_classes = [AuthMfaThrottle]

    @extend_schema(
        request={
            "application/json": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            }
        },
        responses={
            200: inline_serializer(
                "MfaLoginResponse",
                fields={
                    "user": UserAccountSerializer(),
                    "memberships": MembershipSerializer(many=True),
                },
            ),
            400: {"description": "Missing code."},
            401: {"description": "No/invalid/expired challenge, or wrong code."},
        },
        summary="Complete two-step login with the MFA code.",
    )
    def post(self, request: Request) -> Response:
        code = request.data.get("code", "")
        if not code:
            return Response(
                {"detail": "code is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pending = request.session.get("mfa_pending")
        if pending is None:
            return Response(
                {"detail": "no mfa challenge pending for this session."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = _consume_challenge(request)
        if user is None:
            # Expired, malformed, or user-mismatched challenge — fail closed and
            # discard it. Returning the SAME 401 shape for every invalid state
            # gives an attacker no oracle to distinguish them.
            return Response(
                {"detail": "mfa challenge is invalid or expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not user.is_active:
            request.session.flush()
            return Response(
                {"detail": "mfa challenge is invalid or expired."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not MfaService.verify_code(user=user, code=code):
            # Wrong code — do NOT authenticate. The challenge stays valid for
            # further attempts within its window (bounded by AuthMfaThrottle).
            return Response(
                {"detail": "invalid mfa code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Success: consume the challenge and establish the REAL authenticated
        # session. flush() discards the pending state AND rotates the session id
        # before login() (which cycles it again) — the pre-auth identifier never
        # becomes the authenticated one (session-fixation protection).
        request.session.flush()
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


class MemberRevokeView(APIView):
    """Soft-revoke a membership in the current tenant.

    Sets the membership to ``revoked`` and drops its role grants, recording a
    same-transaction ``membership.revoked`` audit entry. Requires ``member.manage``.
    An owner cannot revoke their own last-owner membership (DMS #4 stand-in).
    """

    permission_classes = [IsAuthenticated, HasTenantContext, HasPermission("member.manage")]

    @extend_schema(
        request=None,
        summary="Revoke a membership in the current tenant.",
        responses={204: None},
    )
    def post(self, request: Request, member_id: int) -> Response:
        actor = Membership.objects.get(
            user_account=request.user,
            tenant_id=request.tenant_id,
            status=MembershipStatus.ACTIVE,
        )
        try:
            MembershipService.revoke(
                actor=actor,
                membership_id=member_id,
                reason="revoked via API",
            )
        except (MembershipNotActive, Membership.DoesNotExist):
            return Response(
                {"detail": "membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except LastOwnerSelfRevoke:
            return Response(
                {"detail": "an owner cannot revoke their own last-owner membership."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


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


# ── MFA devices (person-scoped — the deliberate exception to tenant scoping) ─


#: Service exception -> deliberate HTTP mapping. Specific types first; the base
#: ``MfaError`` last so a subclass is never shadowed. Every message is a
#: deliberate service message — internal exceptions and DB errors are never
#: surfaced to the client.
_MFA_EXCEPTION_STATUS = (
    (MfaDeviceNotFound, status.HTTP_404_NOT_FOUND),
    (MfaDeviceRemoved, status.HTTP_409_CONFLICT),
    (MfaDeviceUnverified, status.HTTP_409_CONFLICT),
    (MfaDuplicateDevice, status.HTTP_409_CONFLICT),
    (MfaInvalidCode, status.HTTP_400_BAD_REQUEST),
    (MfaLastDevice, status.HTTP_409_CONFLICT),
    (MfaError, status.HTTP_400_BAD_REQUEST),
)


def _mfa_error_response(exc: MfaError) -> Response:
    """Map a service MFA exception to a deliberate HTTP error response."""
    for cls, code in _MFA_EXCEPTION_STATUS:
        if isinstance(exc, cls):
            return Response({"detail": str(exc)}, status=code)
    return Response(
        {"detail": "mfa request could not be completed"},
        status=status.HTTP_400_BAD_REQUEST,
    )


class MfaDeviceListView(APIView):
    """List the authenticated user's MFA devices (person-scoped, read-only).

    Deliberately NOT tenant-scoped: a device belongs to the person, not the
    tenant. Returns lifecycle state (verified/removed) but never the secret —
    neither the stored ciphertext nor a plaintext.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="The authenticated user's MFA devices.",
        responses={200: MfaDeviceSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        devices = MfaDevice.objects.filter(user_account=request.user).order_by("-created_at")
        return Response(MfaDeviceSerializer(devices, many=True).data)


class MfaEnrollView(APIView):
    """Enroll a new TOTP device for the authenticated user.

    Returns the one-shot provisioning URI (embeds the plaintext secret for the
    user to scan); only the Fernet ciphertext is stored. The write audits into
    the request's tenant context, so a resolved tenant is required.
    """

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=MfaEnrollRequestSerializer,
        summary="Enroll a TOTP device; returns the one-shot provisioning URI.",
        responses={
            201: MfaEnrollResponseSerializer,
            400: {"description": "Invalid enrollment input (blank name, webauthn)."},
            409: {"description": "A device with that name already exists."},
        },
    )
    def post(self, request: Request) -> Response:
        ser = MfaEnrollRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            device, uri = MfaService.enroll(
                user=request.user,
                device_type=ser.validated_data["device_type"],
                name=ser.validated_data["name"],
            )
        except MfaError as exc:
            return _mfa_error_response(exc)
        return Response(
            {"device": MfaDeviceSerializer(device).data, "provisioning_uri": uri},
            status=status.HTTP_201_CREATED,
        )


class MfaVerifyView(APIView):
    """Prove possession of a freshly enrolled device by entering its TOTP code.

    Marks the device verified (idempotent on re-verification). Requires a
    tenant context for the same-transaction audit.
    """

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=MfaVerifyRequestSerializer,
        summary="Verify a freshly enrolled MFA device with a TOTP code.",
        responses={
            204: None,
            400: {"description": "Invalid or expired TOTP code."},
            404: {"description": "Device not found."},
            409: {"description": "Device has been removed."},
        },
    )
    def post(self, request: Request, device_id: int) -> Response:
        ser = MfaVerifyRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            MfaService.verify_initial(
                user=request.user, device_id=device_id, code=ser.validated_data["code"]
            )
        except MfaError as exc:
            return _mfa_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MfaRemoveView(APIView):
    """Soft-remove one of the authenticated user's verified MFA devices.

    Enforces the last-device guard (an MFA-required role cannot be left
    without a device) and the lifecycle invariant (an unverified device cannot
    be removed). Idempotent on an already-removed device.
    """

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=None,
        summary="Remove one of the authenticated user's MFA devices.",
        responses={
            204: None,
            404: {"description": "Device not found."},
            409: {
                "description": "Last verified device while holding an MFA-required "
                "role, or an unverified/removed device."
            },
        },
    )
    def post(self, request: Request, device_id: int) -> Response:
        try:
            MfaService.remove(user=request.user, device_id=device_id)
        except MfaError as exc:
            return _mfa_error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)
