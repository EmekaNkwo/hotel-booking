"""R0.8: the actual pagination mechanism for hand-written ``APIView`` list
endpoints.

``DEFAULT_PAGINATION_CLASS``/``PAGE_SIZE`` were already configured in
settings, but only take effect on ``GenericAPIView``/``ListAPIView``
subclasses that call ``self.paginate_queryset()`` — every list endpoint in
this codebase is a plain ``APIView`` (a deliberate A0 choice: thin,
hand-written views over the service/query layer, not DRF generics), so that
setting was dead config. This module is the smallest addition that makes
pagination real without restructuring any view into a generic class.
"""

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer


def paginate_list(
    request: Request, queryset, serializer_class: type[Serializer]
) -> Response:
    """Paginate ``queryset`` with the project's standard
    ``PageNumberPagination`` (``?page=``, ``PAGE_SIZE`` per page from
    settings) and serialize the current page with ``serializer_class``.

    Response shape: ``{"count", "next", "previous", "results"}`` — DRF's
    standard paginated envelope, consistent across every list endpoint that
    uses this helper.
    """
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True)
    return paginator.get_paginated_response(serializer.data)


def paginated_response_schema(serializer_class: type[Serializer]):
    """R1.4: the ``@extend_schema(responses=...)`` value for a view backed
    by ``paginate_list()`` — every such view is a plain ``APIView``, so
    drf-spectacular never auto-detects ``PageNumberPagination`` the way it
    would for a ``ListAPIView``/``GenericAPIView`` with a
    ``pagination_class``. Without this, the generated OpenAPI schema
    (``/api/schema/``, ``/api/docs/``) would keep describing these
    endpoints as a bare array (``many=True``) when the real runtime
    response is ``{count, next, previous, results}`` — this makes the
    documented contract match the actual one."""
    return inline_serializer(
        name=f"Paginated{serializer_class.__name__}",
        fields={
            "count": serializers.IntegerField(),
            "next": serializers.URLField(allow_null=True),
            "previous": serializers.URLField(allow_null=True),
            "results": serializer_class(many=True),
        },
    )
