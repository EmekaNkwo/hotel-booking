"""Rooms API URL configuration (A0)."""

from django.urls import path

from apps.rooms.api import views

urlpatterns = [
    path("rooms/", views.RoomListView.as_view(), name="api-room-list"),
    path("rooms/<int:room_id>/", views.RoomDetailView.as_view(), name="api-room-detail"),
    path("room-types/", views.RoomTypeListView.as_view(), name="api-room-type-list"),
]
