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
from django.core.cache import cache
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


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """Reset the DRF throttle history between tests.

    ``AnonRateThrottle`` keys on the client IP, which is ``testserver`` for
    every test, and the LocMem cache is process-global — so login attempts
    would otherwise accumulate across tests and 429 the suite after ~20 of
    them. Clearing before and after keeps each test's budget fresh.
    """
    cache.clear()
    yield
    cache.clear()


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


def grant_second_membership(viewer):
    """Give the viewer a second tenant membership (A0 reuse of the M2.3
    ``test_members._grant_viewer_second_tenant`` pattern) — the
    ``X-Tenant-Id``-required 403 only triggers for a multi-membership user;
    a single-membership user resolves tenant context without a header."""
    t2 = Tenant.objects.create(
        code="globex-a0", name="Globex A0", base_currency="NGN", status="active"
    )
    r2 = Role.objects.create(tenant_id=t2.pk, name="staff", status=RoleStatus.PUBLISHED)
    m2 = Membership.objects.create(
        tenant_id=t2.pk, user_account=viewer, status=MembershipStatus.ACTIVE
    )
    RolePermission.objects.create(role=r2, tenant_id=t2.pk, permission_code="member.view")
    MembershipRole.objects.create(membership=m2, role=r2, tenant_id=t2.pk)
    return t2


@pytest.fixture
def a0_world(provisioned):
    """A0: the provisioned tenant plus one sellable property/room-type/room,
    an active rate plan, a published (no-deposit) policy, and a 5-day
    availability horizon starting today — everything the A0 HTTP journey
    (search -> reserve -> book -> allocate -> checkout -> clean) needs.

    Returns a dict keyed by name so tests can pull only what they need.
    """
    import datetime as dt

    from django.utils import timezone

    from apps.availability.services import AvailabilityService
    from apps.policies.services import PolicyService
    from apps.pricing.services import PricingService
    from apps.properties.models import Property
    from apps.rooms.models import Room, RoomType

    tenant, owner, owner_membership, fd_role, viewer, viewer_membership = provisioned

    property_ = Property.objects.create(
        tenant=tenant,
        code="ACME-T1",
        name="Acme Test Hotel",
        status=Property.Status.ACTIVE,
        currency="NGN",
        timezone="UTC",
        check_in_time="14:00",
        check_out_time="12:00",
    )
    room_type = RoomType.objects.create(
        tenant=tenant,
        code="STD",
        name="Standard",
        status=RoomType.Status.ACTIVE,
        max_occupancy=2,
    )
    room = Room.objects.create(
        tenant=tenant,
        property=property_,
        room_type=room_type,
        code="101",
        operational_state=Room.OperationalState.VACANT_CLEAN,
    )
    rate_plan = PricingService.create_rate_plan(
        tenant=tenant,
        property=property_,
        room_type=room_type,
        code="STD-RACK",
        base_rate_minor_units=10000,
        currency=property_.currency,
    )
    PricingService.activate_rate_plan(rate_plan)
    policy = PolicyService.create_draft(tenant, "deposit", {"required": False}, dt.date(2020, 1, 1))
    PolicyService.publish(policy.id)

    today = timezone.now().date()
    AvailabilityService.initialize_horizon(
        tenant_id=tenant.id,
        property_id=property_.id,
        room_type_id=room_type.id,
        total_units=5,
        start_date=today,
        horizon_days=5,
    )

    return {
        "tenant": tenant,
        "owner": owner,
        "owner_membership": owner_membership,
        "fd_role": fd_role,
        "viewer": viewer,
        "viewer_membership": viewer_membership,
        "property": property_,
        "room_type": room_type,
        "room": room,
        "rate_plan": rate_plan,
        "policy": policy,
        "today": today,
    }


@pytest.fixture
def owner_mfa(api, provisioned):
    """The provisioned tenant with the owner MFA-equipped.

    The Step 7 middleware denies an MFA-required role (tenant_owner) whose
    session lacks MFA assurance. RBAC tests that act as the owner use this
    fixture and authenticate with ``login_mfa`` — which walks the full
    password -> challenge -> code flow and stamps the session. The viewer
    (no MFA-required role) is untouched and still logs in with ``login``.
    """
    from tests.api.helpers import equip_owner_with_mfa

    equip_owner_with_mfa(api, OWNER_EMAIL, OWNER_PASSWORD)
    return provisioned
