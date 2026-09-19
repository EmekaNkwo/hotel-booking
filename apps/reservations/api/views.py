"""Reservations API views (A0). Every mutating view delegates to
``ReservationService`` verbatim — no re-implemented guards, no direct
``Reservation``/``ReservationLine`` mutation.

``Reservation`` uses a PLAIN manager (M8: services always pass explicit
``tenant_id`` rather than relying on thread-local scoping), so every read
here filters by ``tenant_id=request.tenant_id`` explicitly — unlike
``apps.rooms``/``apps.guests`` (``TenantScopedManager``, auto-scoped).
"""

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.availability.exceptions import InsufficientAvailability
from apps.policies.services import NoPolicyFound
from apps.properties.models import Property
from apps.reservations.api.serializers import (
    IdempotencyKeyInputSerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
)
from apps.reservations.models import Reservation
from apps.reservations.services import ReservationLineRequest, ReservationService
from apps.rooms.models import RoomType
from apps.shared.api.pagination import paginate_list, paginated_response_schema
from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.value_objects import GuestCount, StayPeriod
from apps.shared.value_objects.exceptions import ValueObjectError
from apps.tenants.models import Tenant


def _get_reservation_or_404(reservation_id: int, tenant_id: int) -> Reservation | Response:
    try:
        return Reservation.objects.prefetch_related("lines").get(
            pk=reservation_id, tenant_id=tenant_id
        )
    except Reservation.DoesNotExist:
        return Response({"detail": "reservation not found."}, status=404)


class ReservationListCreateView(APIView):
    """``GET`` lists, ``POST`` creates (quote + hold via
    ``ReservationService.reserve()``, M8, unmodified).

    The ``GET`` side was added in A2: A0 shipped no way to list reservations
    at all (unlike ``BookingListView``'s equivalent), leaving the UI's
    reservations screen with no contract to call. Same shape as
    ``BookingListView`` — a direct ``tenant_id=`` filter, since ``Reservation``
    is a plain-manager model (M8) like ``Booking``, no new query logic.
    """

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="reservations_list",
        summary="List reservations (tenant-scoped).",
        responses={200: paginated_response_schema(ReservationSerializer)},
    )
    def get(self, request: Request) -> Response:
        qs = Reservation.objects.filter(tenant_id=request.tenant_id).prefetch_related("lines")
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        # R1.5: -id as a deterministic tie-breaker for created_at ties.
        qs = qs.order_by("-created_at", "-id")
        return paginate_list(request, qs, ReservationSerializer)

    @extend_schema(
        request=ReservationCreateSerializer,
        summary="Create a reservation (quote + hold).",
        responses={
            201: ReservationSerializer,
            400: {"description": "Invalid input."},
            404: {"description": "Property or room type not found."},
            409: {"description": "Insufficient availability."},
            422: {"description": "No applicable policy configured for this tenant."},
        },
    )
    def post(self, request: Request) -> Response:
        ser = ReservationCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            property_obj = Property.objects.get(pk=data["property_id"], tenant_id=request.tenant_id)
        except Property.DoesNotExist:
            return Response({"detail": "property not found."}, status=404)

        tenant = Tenant.objects.get(pk=request.tenant_id)
        lines = []
        for line in data["lines"]:
            if not RoomType.objects.filter(
                pk=line["room_type_id"], tenant_id=request.tenant_id
            ).exists():
                return Response(
                    {"detail": f"room type {line['room_type_id']} not found."}, status=404
                )
            try:
                stay_period = StayPeriod(line["arrival_date"], line["departure_date"])
                guest_count = GuestCount(adults=line["adults"], children=line["children"])
            except ValueObjectError as exc:
                return Response({"detail": str(exc)}, status=400)
            lines.append(
                ReservationLineRequest(
                    room_type_id=line["room_type_id"],
                    stay_period=stay_period,
                    guest_count=guest_count,
                    quantity=line["quantity"],
                )
            )

        idempotency_key = data["idempotency_key"] or str(uuid.uuid4())
        try:
            reservation = ReservationService.reserve(
                tenant=tenant,
                property=property_obj,
                lines=lines,
                idempotency_key=idempotency_key,
                guest_email=data["guest_email"],
                guest_phone=data["guest_phone"],
            )
        except InsufficientAvailability as exc:
            return Response({"detail": str(exc)}, status=409)
        except NoPolicyFound as exc:
            return Response({"detail": str(exc)}, status=422)
        except (ValueError, ValueObjectError) as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(ReservationSerializer(reservation).data, status=201)


class ReservationDetailView(APIView):
    """One reservation (tenant-scoped)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="reservations_retrieve",
        summary="Reservation detail.",
        responses={200: ReservationSerializer, 404: {"description": "Reservation not found."}},
    )
    def get(self, request: Request, reservation_id: int) -> Response:
        result = _get_reservation_or_404(reservation_id, request.tenant_id)
        if isinstance(result, Response):
            return result
        return Response(ReservationSerializer(result).data)


class ReservationRequestPaymentView(APIView):
    """``Held -> Awaiting_Payment`` — ``ReservationService.request_payment()``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=None,
        summary="Move a reservation to Awaiting_Payment.",
        responses={
            200: ReservationSerializer,
            404: {"description": "Reservation not found."},
            409: {"description": "Reservation is not in a state that allows this transition."},
        },
    )
    def post(self, request: Request, reservation_id: int) -> Response:
        result = _get_reservation_or_404(reservation_id, request.tenant_id)
        if isinstance(result, Response):
            return result
        try:
            updated = ReservationService.request_payment(
                reservation_id, tenant_id=request.tenant_id
            )
        except TransitionNotAllowed as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(ReservationSerializer(updated).data)


class ReservationCancelView(APIView):
    """Hold abandonment — ``ReservationService.cancel()`` (idempotency-keyed)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=IdempotencyKeyInputSerializer,
        summary="Cancel a reservation (hold abandonment, no penalty).",
        responses={200: ReservationSerializer, 404: {"description": "Reservation not found."}},
    )
    def post(self, request: Request, reservation_id: int) -> Response:
        result = _get_reservation_or_404(reservation_id, request.tenant_id)
        if isinstance(result, Response):
            return result
        ser = IdempotencyKeyInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        idempotency_key = ser.validated_data["idempotency_key"] or str(uuid.uuid4())
        cancelled = ReservationService.cancel(
            tenant_id=request.tenant_id,
            reservation_id=reservation_id,
            idempotency_key=idempotency_key,
        )
        return Response(ReservationSerializer(cancelled).data)
