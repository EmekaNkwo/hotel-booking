"""Housekeeping API URL configuration (A0)."""

from django.urls import path

from apps.housekeeping.api import views

urlpatterns = [
    path(
        "housekeeping/checkout/",
        views.HousekeepingCheckoutView.as_view(),
        name="api-housekeeping-checkout",
    ),
    path(
        "housekeeping/tasks/",
        views.HousekeepingTaskListView.as_view(),
        name="api-housekeeping-task-list",
    ),
    path(
        "housekeeping/tasks/<int:task_id>/",
        views.HousekeepingTaskDetailView.as_view(),
        name="api-housekeeping-task-detail",
    ),
    path(
        "housekeeping/tasks/<int:task_id>/start-cleaning/",
        views.HousekeepingStartCleaningView.as_view(),
        name="api-housekeeping-start-cleaning",
    ),
    path(
        "housekeeping/tasks/<int:task_id>/complete-cleaning/",
        views.HousekeepingCompleteCleaningView.as_view(),
        name="api-housekeeping-complete-cleaning",
    ),
    path(
        "housekeeping/tasks/<int:task_id>/inspect/",
        views.HousekeepingInspectView.as_view(),
        name="api-housekeeping-inspect",
    ),
]
