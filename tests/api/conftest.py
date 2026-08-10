"""Shared fixtures for the M2.3 API tests.

The test flow mirrors production:
1. Provision a tenant (via TenantService — idempotent composite).
2. Create a user with a password and an active membership carrying a role.
3. ``client.post("/api/auth/login/", ...)`` — establishes the session cookie.
4. Subsequent requests carry the cookie → ``TenantContextMiddleware`` resolves
   tenant context from the user's active memberships + ``X-Tenant-Id`` header.

The ``APIClient`` (DRF) maintains cookies automatically, so one login call
covers the whole test.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    RolePermission,
    RoleStatus,
)
from apps.tenants.models import Tenant
from apps.tenants.services import TenantService

UserAccount = get_user_model()
OWNER_EMAIL = "owner@acme.example"
OWNER_PASSWORD = "Owner!pw123!"
VIEWER_EMAIL = "viewer@acme.example"
VIEWER_PASSWORD = "Viewer!pw123!"


@pytest.fixture
def api():
    """An unauthenticated DRF test client (session-based)."""
    return APIClient()


@pytest.fixture
def provisioned():
    """Provision a tenant with two users (owner + viewer) and return everything.

    The owner carries ``tenant_owner`` (all tenant-scoped permissions);
    the viewer carries ``front_desk`` (only ``member.view``).
    Returns ``(tenant, owner_user, owner_membership, fd_role, viewer_user,
    viewer_membership)``.
    """
    TenantService.provision(
        code="acme",
        name="Acme Hotels",
        base_currency="NGN",
        owner_email=OWNER_EMAIL,
    )
    tenant = Tenant.objects.get()
    owner = UserAccount.objects.get(email=OWNER_EMAIL)
    owner.set_password(OWNER_PASSWORD)
    owner.save()
    owner_membership = Membership.objects.get(tenant_id=tenant.pk, user_account=owner)

    viewer = UserAccount.objects.create_user(email=VIEWER_EMAIL, password=VIEWER_PASSWORD)
    fd_role = Role.objects.create(
        tenant_id=tenant.pk, name="front_desk", status=RoleStatus.PUBLISHED
    )
    RolePermission.objects.create(role=fd_role, tenant_id=tenant.pk, permission_code="member.view")
    viewer_membership = Membership.objects.create(
        tenant_id=tenant.pk, user_account=viewer, status=MembershipStatus.ACTIVE
    )
    MembershipRole.objects.create(membership=viewer_membership, role=fd_role, tenant_id=tenant.pk)

    return (
        tenant,
        owner,
        owner_membership,
        fd_role,
        viewer,
        viewer_membership,
    )
