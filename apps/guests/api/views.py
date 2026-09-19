"""Guests API views (A0). Creation delegates to ``GuestService.resolve()``
(find-or-create by identity, M5) — never a raw ``GuestProfile.objects.create``."""

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.guests.api.serializers import GuestCreateSerializer, GuestProfileSerializer
from apps.guests.models import GuestProfile
from apps.guests.services import GuestResolutionError, GuestService
from apps.shared.api.pagination import paginate_list, paginated_response_schema
from apps.shared.value_objects import GuestName
from apps.shared.value_objects.exceptions import ValueObjectError
from apps.tenants.models import Tenant


class GuestListView(APIView):
    """Guests in the current tenant. ``?q=`` searches email/phone
    (case-insensitive substring — a search box's minimum useful behavior)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="guests_list",
        summary="List/search guests (tenant-scoped).",
        responses={200: paginated_response_schema(GuestProfileSerializer)},
    )
    def get(self, request: Request) -> Response:
        qs = GuestProfile.objects.filter(erased_at__isnull=True)
        query = request.query_params.get("q", "").strip()
        if query:
            qs = qs.filter(Q(primary_email__icontains=query) | Q(primary_phone__icontains=query))
        # R1.5: -id as a deterministic tie-breaker for created_at ties.
        qs = qs.order_by("-created_at", "-id")
        return paginate_list(request, qs, GuestProfileSerializer)


class GuestCreateView(APIView):
    """Find-or-create a guest by email/phone (``GuestService.resolve()``)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=GuestCreateSerializer,
        summary="Find-or-create a guest by identity.",
        responses={201: GuestProfileSerializer, 400: {"description": "Invalid input."}},
    )
    def post(self, request: Request) -> Response:
        ser = GuestCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        name = None
        if data["given_name"]:
            name = GuestName(given_name=data["given_name"], family_name=data["family_name"])

        tenant = Tenant.objects.get(pk=request.tenant_id)
        try:
            guest = GuestService.resolve(
                tenant,
                email=data["email"],
                phone=data["phone"],
                name=name,
                language=data["language"],
            )
        except (GuestResolutionError, ValueObjectError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(GuestProfileSerializer(guest).data, status=201)


class GuestDetailView(APIView):
    """One guest (tenant-scoped)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="guests_retrieve",
        summary="Guest detail.",
        responses={200: GuestProfileSerializer, 404: {"description": "Guest not found."}},
    )
    def get(self, request: Request, guest_id: int) -> Response:
        try:
            guest = GuestProfile.objects.get(pk=guest_id)
        except GuestProfile.DoesNotExist:
            return Response({"detail": "guest not found."}, status=404)
        return Response(GuestProfileSerializer(guest).data)
