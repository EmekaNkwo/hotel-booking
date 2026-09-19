"""Reservations API URL configuration (A0)."""

from django.urls import path

from apps.reservations.api import views

urlpatterns = [
    path(
        "reservations/",
        views.ReservationListCreateView.as_view(),
        name="api-reservation-list-create",
    ),
    path(
        "reservations/<int:reservation_id>/",
        views.ReservationDetailView.as_view(),
        name="api-reservation-detail",
    ),
    path(
        "reservations/<int:reservation_id>/request-payment/",
        views.ReservationRequestPaymentView.as_view(),
        name="api-reservation-request-payment",
    ),
    path(
        "reservations/<int:reservation_id>/cancel/",
        views.ReservationCancelView.as_view(),
        name="api-reservation-cancel",
    ),
]
