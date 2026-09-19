"""Allocation API views (A0). ``AllocationService.allocate_line()`` is
unmodified — this view adds no candidate-selection logic of its own.
``AllocationRecord`` uses a PLAIN manager (M11) — reads scope through the
``BookingLine``'s tenant, matching the M11 service's own tenant handling."""

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.allocation.api.serializers import AllocateLineSerializer, AllocationRecordSerializer
from apps.allocation.exceptions import BookingLineNotAllocatable, NoEligibleRoom
from apps.allocation.services import AllocationQuery, AllocationService
from apps.bookings.models import BookingLine


class AllocateLineView(APIView):
    """Assign a physical room to a BookingLine — ``AllocationService.allocate_line()``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=AllocateLineSerializer,
        summary="Allocate a physical room to a confirmed BookingLine.",
        responses={
            201: AllocationRecordSerializer,
            404: {"description": "Booking line not found."},
            409: {"description": "No eligible room, or the line is already allocated."},
        },
    )
    def post(self, request: Request) -> Response:
        ser = AllocateLineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        if not BookingLine.objects.filter(
            pk=data["booking_line_id"], booking__tenant_id=request.tenant_id
        ).exists():
            return Response({"detail": "booking line not found."}, status=404)

        idempotency_key = data["idempotency_key"] or str(uuid.uuid4())
        try:
            record = AllocationService.allocate_line(
                tenant_id=request.tenant_id,
                booking_line_id=data["booking_line_id"],
                idempotency_key=idempotency_key,
            )
        except (NoEligibleRoom, BookingLineNotAllocatable) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(AllocationRecordSerializer(record).data, status=201)


class AllocationByBookingLineView(APIView):
    """The allocation decision for one BookingLine, if any."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        summary="Allocation record for a booking line.",
        responses={
            200: AllocationRecordSerializer,
            404: {"description": "Booking line not found, or not yet allocated."},
        },
    )
    def get(self, request: Request, booking_line_id: int) -> Response:
        try:
            booking_line = BookingLine.objects.get(
                pk=booking_line_id, booking__tenant_id=request.tenant_id
            )
        except BookingLine.DoesNotExist:
            return Response({"detail": "booking line not found."}, status=404)

        record = AllocationQuery.by_booking_line(booking_line)
        if record is None:
            return Response({"detail": "no allocation for this booking line."}, status=404)
        return Response(AllocationRecordSerializer(record).data)
