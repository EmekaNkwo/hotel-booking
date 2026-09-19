"""Bookings API views (A0). ``BookingService.confirm()`` composes
``ReservationService.convert()`` — this view adds no orchestration of its
own beyond mapping ``Reservation.DoesNotExist`` to a 404 (R0.1:
``convert()`` now filters its lookup by ``tenant_id`` itself, so this is
the same exception whether the id is wrong-tenant or truly nonexistent).
``Booking`` uses a PLAIN manager (M9, same reasoning as Reservation) —
every read filters by ``tenant_id`` explicitly.
"""

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.bookings.api.serializers import BookingConfirmSerializer, BookingSerializer
from apps.bookings.models import Booking
from apps.bookings.services import BookingService
from apps.reservations.models import Reservation
from apps.shared.api.pagination import paginate_list, paginated_response_schema
from apps.shared.exceptions import TransitionNotAllowed


class BookingListView(APIView):
    """Bookings in the current tenant. Optional ``?status=``, ``?arrival_date=``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="bookings_list",
        summary="List bookings (tenant-scoped).",
        responses={200: paginated_response_schema(BookingSerializer)},
    )
    def get(self, request: Request) -> Response:
        qs = Booking.objects.filter(tenant_id=request.tenant_id).prefetch_related("lines")
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(aggregate_status=status_param)
        # R1.2: the aggregate's own arrival_date (indexed together with
        # property/aggregate_status — see Booking.Meta.indexes) — a minimal
        # filter, not a new selector; distinct from BookingQuery
        # .arrivals_for_property()'s line-level "confirmed/checked_in
        # today" semantics, which this list endpoint (aggregate-level,
        # unfiltered by line status) does not attempt to replicate.
        arrival_date = request.query_params.get("arrival_date")
        if arrival_date:
            qs = qs.filter(arrival_date=arrival_date)
        # R1.5: -id as a deterministic tie-breaker for created_at ties.
        qs = qs.order_by("-created_at", "-id")
        return paginate_list(request, qs, BookingSerializer)


class BookingDetailView(APIView):
    """One booking (tenant-scoped)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="bookings_retrieve",
        summary="Booking detail.",
        responses={200: BookingSerializer, 404: {"description": "Booking not found."}},
    )
    def get(self, request: Request, booking_id: int) -> Response:
        try:
            booking = Booking.objects.prefetch_related("lines").get(
                pk=booking_id, tenant_id=request.tenant_id
            )
        except Booking.DoesNotExist:
            return Response({"detail": "booking not found."}, status=404)
        return Response(BookingSerializer(booking).data)


class BookingConfirmView(APIView):
    """Convert a reservation into a committed Booking (payment pending) —
    ``BookingService.confirm()``, unmodified."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=BookingConfirmSerializer,
        summary="Confirm a booking from an Awaiting_Payment reservation.",
        responses={
            201: BookingSerializer,
            404: {"description": "Reservation not found."},
            409: {"description": "Reservation is not Awaiting_Payment, or already converted."},
        },
    )
    def post(self, request: Request) -> Response:
        ser = BookingConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        idempotency_key = data["idempotency_key"] or str(uuid.uuid4())
        try:
            booking = BookingService.confirm(
                tenant_id=request.tenant_id,
                reservation_id=data["reservation_id"],
                idempotency_key=idempotency_key,
            )
        except Reservation.DoesNotExist:
            # R0.1: ReservationService.convert() now filters by tenant_id,
            # so a reservation_id belonging to another tenant raises this
            # identically to a genuinely nonexistent one — the response
            # must not let a caller distinguish the two.
            return Response({"detail": "reservation not found."}, status=404)
        except TransitionNotAllowed as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(BookingSerializer(booking).data, status=201)
