"""Properties API views (A2 addition to the A0 thin HTTP surface). Read-only
— thin wrappers over ``Property.objects`` (``TenantScopedManager``, M3),
exactly matching ``apps.rooms.api``'s conventions. No business logic beyond
what A0's own equivalent views already established."""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.properties.api.serializers import PropertySerializer
from apps.properties.models import Property


class PropertyListView(APIView):
    """Active properties in the current tenant."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        summary="List active properties (tenant-scoped).",
        responses={200: PropertySerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        qs = Property.objects.filter(status=Property.Status.ACTIVE).order_by("name")
        return Response(PropertySerializer(qs, many=True).data)


class PropertyDetailView(APIView):
    """One property (tenant-scoped)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        summary="Property detail.",
        responses={200: PropertySerializer, 404: {"description": "Property not found."}},
    )
    def get(self, request: Request, property_id: int) -> Response:
        try:
            property_obj = Property.objects.get(pk=property_id)
        except Property.DoesNotExist:
            return Response({"detail": "property not found."}, status=404)
        return Response(PropertySerializer(property_obj).data)
