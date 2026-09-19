"""Rooms API views (A0). Thin — every read goes straight through the
tenant-scoped ``Room``/``RoomType`` managers (M3); no new query logic."""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.rooms.api.serializers import RoomSerializer, RoomTypeSerializer
from apps.rooms.models import Room, RoomType
from apps.shared.api.pagination import paginate_list, paginated_response_schema


class RoomListView(APIView):
    """Rooms in the current tenant — the room status board's data source.

    Optional filters: ``property_id``, ``room_type_id``, ``operational_state``.
    """

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="rooms_list",
        summary="List rooms (tenant-scoped).",
        responses={200: paginated_response_schema(RoomSerializer)},
    )
    def get(self, request: Request) -> Response:
        qs = Room.objects.filter(deleted_at__isnull=True).select_related("room_type")
        property_id = request.query_params.get("property_id")
        room_type_id = request.query_params.get("room_type_id")
        operational_state = request.query_params.get("operational_state")
        if property_id:
            qs = qs.filter(property_id=property_id)
        if room_type_id:
            qs = qs.filter(room_type_id=room_type_id)
        if operational_state:
            qs = qs.filter(operational_state=operational_state)
        # R1.5: `code` is only unique per-property (unique_room_code_per_property),
        # not tenant-wide, so a multi-property tenant's unfiltered list can
        # tie on code across properties — -id breaks the tie deterministically.
        qs = qs.order_by("code", "id")
        return paginate_list(request, qs, RoomSerializer)


class RoomDetailView(APIView):
    """One room (tenant-scoped)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="rooms_retrieve",
        summary="Room detail.",
        responses={200: RoomSerializer, 404: {"description": "Room not found."}},
    )
    def get(self, request: Request, room_id: int) -> Response:
        try:
            room = Room.objects.select_related("room_type").get(pk=room_id)
        except Room.DoesNotExist:
            return Response({"detail": "room not found."}, status=404)
        return Response(RoomSerializer(room).data)


class RoomTypeListView(APIView):
    """Active room types in the current tenant."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        summary="List active room types (tenant-scoped).",
        responses={200: RoomTypeSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        qs = RoomType.objects.filter(status=RoomType.Status.ACTIVE).order_by("code")
        return Response(RoomTypeSerializer(qs, many=True).data)
