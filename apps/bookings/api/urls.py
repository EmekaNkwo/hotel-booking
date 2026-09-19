"""Bookings API URL configuration (A0)."""

from django.urls import path

from apps.bookings.api import views

urlpatterns = [
    path("bookings/", views.BookingListView.as_view(), name="api-booking-list"),
    path("bookings/confirm/", views.BookingConfirmView.as_view(), name="api-booking-confirm"),
    path(
        "bookings/<int:booking_id>/", views.BookingDetailView.as_view(), name="api-booking-detail"
    ),
]
