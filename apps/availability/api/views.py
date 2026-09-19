"""Availability API views (A0).

Composes the SAME two read-only calls the backend already composes
internally (SDD S11.5's own pipeline: availability filters, pricing
attaches) — ``AvailabilityQuery`` (M7) + ``PricingService.price()`` (M6).
No new composition logic is invented here beyond calling both and shaping
one HTTP response; a missing rate plan is reported as ``price: null`` with
an explanatory ``price_error``, never a 500.
"""

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import HasTenantContext
from apps.availability.api.serializers import AvailabilitySearchSerializer
from apps.availability.services import AvailabilityQuery
from apps.pricing.services import (
    NoRatePlanFound,
    PricingService,
    RatePlanCurrencyMismatch,
    RatePlanNotActive,
)
from apps.properties.models import Property
from apps.rooms.models import RoomType
from apps.shared.value_objects import DateRange, GuestCount, StayPeriod
from apps.shared.value_objects.exceptions import ValueObjectError


class AvailabilitySearchView(APIView):
    """Remaining capacity + price for a property/room-type/date-range —
    the search-and-quote screen's one call."""

    permission_classes = [IsAuthenticated, HasTenantContext]

    @extend_schema(
        summary="Search availability and price (tenant-scoped).",
        parameters=[AvailabilitySearchSerializer],
        responses={
            200: inline_serializer(
                "AvailabilitySearchResponse",
                fields={
                    "property_id": serializers.IntegerField(),
                    "room_type_id": serializers.IntegerField(),
                    "start": serializers.DateField(),
                    "end": serializers.DateField(),
                    "quantity": serializers.IntegerField(),
                    "sellable": serializers.BooleanField(),
                    "remaining_by_date": serializers.DictField(),
                    "price": serializers.DictField(allow_null=True),
                    "price_error": serializers.CharField(allow_null=True),
                },
            ),
            400: {"description": "Invalid search parameters."},
            404: {"description": "Property or room type not found."},
        },
    )
    def get(self, request: Request) -> Response:
        ser = AvailabilitySearchSerializer(data=request.query_params)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        try:
            date_range = DateRange(data["start"], data["end"])
        except ValueObjectError as exc:
            return Response({"detail": str(exc)}, status=400)

        try:
            property_obj = Property.objects.get(pk=data["property_id"])
        except Property.DoesNotExist:
            return Response({"detail": "property not found."}, status=404)
        try:
            room_type = RoomType.objects.get(pk=data["room_type_id"])
        except RoomType.DoesNotExist:
            return Response({"detail": "room type not found."}, status=404)

        remaining = AvailabilityQuery.remaining_for_range(
            tenant_id=request.tenant_id,
            property_id=data["property_id"],
            room_type_id=data["room_type_id"],
            date_range=date_range,
        )
        sellable = AvailabilityQuery.is_sellable(
            tenant_id=request.tenant_id,
            property_id=data["property_id"],
            room_type_id=data["room_type_id"],
            date_range=date_range,
            quantity=data["quantity"],
        )

        price = None
        price_error = None
        try:
            stay_period = StayPeriod(data["start"], data["end"])
            guest_count = GuestCount(adults=data["adults"], children=data["children"])
            breakdown = PricingService.price(property_obj, room_type, stay_period, guest_count)
            price = breakdown.to_dict()
        except (
            NoRatePlanFound,
            RatePlanNotActive,
            RatePlanCurrencyMismatch,
            ValueObjectError,
        ) as exc:
            price_error = str(exc)

        return Response(
            {
                "property_id": data["property_id"],
                "room_type_id": data["room_type_id"],
                "start": data["start"].isoformat(),
                "end": data["end"].isoformat(),
                "quantity": data["quantity"],
                "sellable": sellable,
                "remaining_by_date": {d.isoformat(): r for d, r in remaining.items()},
                "price": price,
                "price_error": price_error,
            }
        )
