"""Accounts API URL configuration (M2.3).

Each route is named and documented — the schema endpoint sees them all via
``drf-spectacular``.
"""

from django.urls import path

from apps.accounts.api import views

urlpatterns = [
    path("auth/login/", views.LoginView.as_view(), name="api-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="api-logout"),
    path("auth/me/", views.MeView.as_view(), name="api-me"),
    # --- Cross-tenant read (the deliberate exception to tenant scoping) ---
    path("tenants/", views.TenantMembershipView.as_view(), name="api-tenant-list"),
    # --- Tenant-scoped endpoints ---
    path("members/", views.MemberListView.as_view(), name="api-member-list"),
    path("members/invite/", views.InviteMemberView.as_view(), name="api-invite-member"),
    path(
        "members/<int:member_id>/revoke/",
        views.MemberRevokeView.as_view(),
        name="api-revoke-member",
    ),
    path("roles/", views.RoleListView.as_view(), name="api-role-list"),
    path("roles/create/", views.RoleCreateView.as_view(), name="api-role-create"),
]
