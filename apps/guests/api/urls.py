"""Guests API URL configuration (A0)."""

from django.urls import path

from apps.guests.api import views

urlpatterns = [
    path("guests/", views.GuestListView.as_view(), name="api-guest-list"),
    path("guests/create/", views.GuestCreateView.as_view(), name="api-guest-create"),
    path("guests/<int:guest_id>/", views.GuestDetailView.as_view(), name="api-guest-detail"),
]
