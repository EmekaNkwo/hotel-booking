"""Housekeeping API views (A0). Every mutating view delegates to
``HousekeepingService`` verbatim — the task/Room FSM pair advances exactly
as it does when called from Python. ``HousekeepingTask`` uses
``TenantScopedManager`` (M12) and is auto-scoped by the request's tenant
context; ``BookingLine`` (M9) is a plain manager and is scoped explicitly
through its ``booking__tenant_id``.
"""

import uuid

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.bookings.models import BookingLine
from apps.housekeeping.api.serializers import (
    CheckoutSerializer,
    HousekeepingTaskSerializer,
    InspectSerializer,
    TaskActionSerializer,
)
from apps.housekeeping.models import HousekeepingTask
from apps.housekeeping.services import HousekeepingService, TaskNotTransitionable
from apps.shared.api.pagination import paginate_list, paginated_response_schema
from apps.shared.exceptions import ConcurrencyError, TransitionNotAllowed


def _get_task_or_404(task_id: int) -> HousekeepingTask | Response:
    try:
        return HousekeepingTask.objects.get(pk=task_id)
    except HousekeepingTask.DoesNotExist:
        return Response({"detail": "housekeeping task not found."}, status=404)


class HousekeepingCheckoutView(APIView):
    """Check a guest's line out and open the departure cleaning task —
    ``HousekeepingService.check_out_and_create_task()``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=CheckoutSerializer,
        summary="Check out a BookingLine and create its departure task.",
        responses={
            201: HousekeepingTaskSerializer,
            404: {"description": "Booking line not found."},
            409: {"description": "Line is not checked_in, or already checked out."},
        },
    )
    def post(self, request: Request) -> Response:
        ser = CheckoutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        if not BookingLine.objects.filter(
            pk=data["booking_line_id"], booking__tenant_id=request.tenant_id
        ).exists():
            return Response({"detail": "booking line not found."}, status=404)

        idempotency_key = data["idempotency_key"] or str(uuid.uuid4())
        try:
            task = HousekeepingService.check_out_and_create_task(
                tenant_id=request.tenant_id,
                booking_line_id=data["booking_line_id"],
                idempotency_key=idempotency_key,
            )
        except TaskNotTransitionable as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(HousekeepingTaskSerializer(task).data, status=201)


class HousekeepingTaskListView(APIView):
    """Housekeeping tasks (tenant-scoped). Optional ``?status=``, ``?room_id=``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="housekeeping_tasks_list",
        summary="List housekeeping tasks (tenant-scoped).",
        responses={200: paginated_response_schema(HousekeepingTaskSerializer)},
    )
    def get(self, request: Request) -> Response:
        qs = HousekeepingTask.objects.all()
        status_param = request.query_params.get("status")
        room_id = request.query_params.get("room_id")
        if status_param:
            qs = qs.filter(status=status_param)
        if room_id:
            qs = qs.filter(room_id=room_id)
        # R1.5: -id as a deterministic final tie-breaker — business_date
        # and created_at together can still tie (a batch of tasks created
        # for the same checkout run), which would otherwise let
        # PageNumberPagination duplicate or skip rows across pages.
        qs = qs.order_by("-business_date", "-created_at", "-id")
        return paginate_list(request, qs, HousekeepingTaskSerializer)


class HousekeepingTaskDetailView(APIView):
    """One housekeeping task."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="housekeeping_tasks_retrieve",
        summary="Housekeeping task detail.",
        responses={200: HousekeepingTaskSerializer, 404: {"description": "Task not found."}},
    )
    def get(self, request: Request, task_id: int) -> Response:
        result = _get_task_or_404(task_id)
        if isinstance(result, Response):
            return result
        return Response(HousekeepingTaskSerializer(result).data)


class HousekeepingStartCleaningView(APIView):
    """``planned/assigned -> in_progress`` — ``HousekeepingService.start_cleaning()``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=TaskActionSerializer,
        summary="Start cleaning a room.",
        responses={
            200: HousekeepingTaskSerializer,
            404: {"description": "Task not found."},
            409: {"description": "Task is not planned/assigned, or a concurrent update won."},
        },
    )
    def post(self, request: Request, task_id: int) -> Response:
        result = _get_task_or_404(task_id)
        if isinstance(result, Response):
            return result
        ser = TaskActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        idempotency_key = ser.validated_data["idempotency_key"] or str(uuid.uuid4())
        try:
            task = HousekeepingService.start_cleaning(
                tenant_id=request.tenant_id, task_id=task_id, idempotency_key=idempotency_key
            )
        except (TaskNotTransitionable, TransitionNotAllowed, ConcurrencyError) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(HousekeepingTaskSerializer(task).data)


class HousekeepingCompleteCleaningView(APIView):
    """``in_progress -> quality_check`` — ``HousekeepingService.complete_cleaning()``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=TaskActionSerializer,
        summary="Mark cleaning complete; room awaits inspection.",
        responses={
            200: HousekeepingTaskSerializer,
            404: {"description": "Task not found."},
            409: {"description": "Task is not in_progress, or a concurrent update won."},
        },
    )
    def post(self, request: Request, task_id: int) -> Response:
        result = _get_task_or_404(task_id)
        if isinstance(result, Response):
            return result
        ser = TaskActionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        idempotency_key = ser.validated_data["idempotency_key"] or str(uuid.uuid4())
        try:
            task = HousekeepingService.complete_cleaning(
                tenant_id=request.tenant_id, task_id=task_id, idempotency_key=idempotency_key
            )
        except (TaskNotTransitionable, TransitionNotAllowed, ConcurrencyError) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(HousekeepingTaskSerializer(task).data)


class HousekeepingInspectView(APIView):
    """Record the inspection verdict — ``HousekeepingService.inspect()``.
    Pass moves the room to ``VACANT_CLEAN``; fail sends it back to
    ``CLEANING`` (no OOS routing — M12 ruling)."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        request=InspectSerializer,
        summary="Record an inspection result (pass/fail).",
        responses={
            200: HousekeepingTaskSerializer,
            404: {"description": "Task not found."},
            409: {"description": "Task is not in quality_check, or a concurrent update won."},
        },
    )
    def post(self, request: Request, task_id: int) -> Response:
        result = _get_task_or_404(task_id)
        if isinstance(result, Response):
            return result
        ser = InspectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        idempotency_key = data["idempotency_key"] or str(uuid.uuid4())
        try:
            task = HousekeepingService.inspect(
                tenant_id=request.tenant_id,
                task_id=task_id,
                result=data["result"],
                idempotency_key=idempotency_key,
            )
        except (TaskNotTransitionable, TransitionNotAllowed, ConcurrencyError) as exc:
            return Response({"detail": str(exc)}, status=409)
        return Response(HousekeepingTaskSerializer(task).data)
