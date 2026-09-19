"""Notifications API views (A0). Read-only — staff visibility into
delivery/DLQ status; nothing here triggers a send (that stays
Celery/projector-driven, M13). ``NotificationJob`` uses a PLAIN manager
(M13) — scoped explicitly by ``tenant_id``."""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.notifications.api.serializers import NotificationJobSerializer
from apps.notifications.models import NotificationJob
from apps.shared.api.pagination import paginate_list, paginated_response_schema


class NotificationJobListView(APIView):
    """Notification jobs (tenant-scoped). Optional ``?status=``."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="notifications_list",
        summary="List notification jobs (tenant-scoped).",
        responses={200: paginated_response_schema(NotificationJobSerializer)},
    )
    def get(self, request: Request) -> Response:
        qs = NotificationJob.objects.filter(tenant_id=request.tenant_id)
        status_param = request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        # R1.5: -id as a deterministic tie-breaker — created_at alone can
        # tie (e.g. a batch of jobs projected from the same event in one
        # transaction), which would otherwise let PageNumberPagination
        # duplicate or skip rows across page boundaries.
        qs = qs.order_by("-created_at", "-id")
        return paginate_list(request, qs, NotificationJobSerializer)


class NotificationJobDetailView(APIView):
    """One notification job."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        operation_id="notifications_retrieve",
        summary="Notification job detail.",
        responses={200: NotificationJobSerializer, 404: {"description": "Job not found."}},
    )
    def get(self, request: Request, job_id: int) -> Response:
        try:
            job = NotificationJob.objects.get(pk=job_id, tenant_id=request.tenant_id)
        except NotificationJob.DoesNotExist:
            return Response({"detail": "notification job not found."}, status=404)
        return Response(NotificationJobSerializer(job).data)
