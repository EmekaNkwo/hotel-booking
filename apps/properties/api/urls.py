"""Properties API URL configuration (A2 addition)."""

from django.urls import path

from apps.properties.api import views

urlpatterns = [
    path("properties/", views.PropertyListView.as_view(), name="api-property-list"),
    path(
        "properties/<int:property_id>/",
        views.PropertyDetailView.as_view(),
        name="api-property-detail",
    ),
]
