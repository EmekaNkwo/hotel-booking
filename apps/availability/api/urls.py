"""Availability API URL configuration (A0)."""

from django.urls import path

from apps.availability.api import views

urlpatterns = [
    path("availability/", views.AvailabilitySearchView.as_view(), name="api-availability-search"),
]
