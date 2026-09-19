"""Notifications API URL configuration (A0)."""

from django.urls import path

from apps.notifications.api import views

urlpatterns = [
    path("notifications/", views.NotificationJobListView.as_view(), name="api-notification-list"),
    path(
        "notifications/<int:job_id>/",
        views.NotificationJobDetailView.as_view(),
        name="api-notification-detail",
    ),
]
