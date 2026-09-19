"""Allocation API URL configuration (A0)."""

from django.urls import path

from apps.allocation.api import views

urlpatterns = [
    path("allocation/allocate/", views.AllocateLineView.as_view(), name="api-allocate-line"),
    path(
        "allocation/by-booking-line/<int:booking_line_id>/",
        views.AllocationByBookingLineView.as_view(),
        name="api-allocation-by-booking-line",
    ),
]
