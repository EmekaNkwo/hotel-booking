"""Unit tests for InvitationService — create/resend/revoke (M2.2).

Order: creation (token hygiene, role scope, permission, audit) → resend →
revoke → guards.
"""

import hashlib
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.exceptions import (
    InsufficientPermission,
    InvitationError,
    InvitationNotPending,
)
from apps.accounts.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
    RolePermission,
)
from apps.accounts.permissions import Permissions
from apps.accounts.services import InvitationService
from apps.shared.models import AuditLog
from apps.tenants.services import TenantService

TENANT = {
    "code": "acme",
    "name": "Acme Hotels",
    "base_currency": "NGN",
    "owner_email": "owner@acme.example",
}
INVITEE_EMAIL = "Desk.Agent@acme.example"


@pytest.fixture
def inviter():
    """A provisioned tenant whose owner membership can invite and manage."""
    TenantService.provision(**TENANT)
    return Membership.objects.get(tenant_id=1)


@pytest.fixture
def target_role():
    return Role.objects.create(tenant_id=1, name="front_desk")


@pytest.fixture
def pending_invite(inviter, target_role):
    invitation, token = InvitationService.create(
        inviter=inviter,
        email=INVITEE_EMAIL,
        role=target_role,
        expires_at=timezone.now() + timedelta(days=7),
    )
    return invitation, token


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class TestCreate:
    @pytest.mark.django_db
    def test_returns_a_token_distinct_from_its_stored_hash(self, inviter, target_role):
        invitation, token = InvitationService.create(
            inviter=inviter,
            email=INVITEE_EMAIL,
            role=target_role,
            expires_at=timezone.now() + timedelta(days=7),
        )

        assert token
        assert token != invitation.token_hash
        assert invitation.token_hash == _sha256(token)

    @pytest.mark.django_db
    def test_stores_nothing_that_can_reverse_to_the_token(self, inviter, target_role):
        _, token = InvitationService.create(
            inviter=inviter,
            email=INVITEE_EMAIL,
            role=target_role,
            expires_at=timezone.now() + timedelta(days=7),
        )

        assert Invitation.objects.exclude(token_hash=_sha256(token)).count() == 0

    @pytest.mark.django_db
    def test_normalizes_email_and_defaults_to_pending(self, inviter, target_role):
        invitation, _ = InvitationService.create(
            inviter=inviter,
            email="  Desk.Agent@acme.example  ",
            role=target_role,
            expires_at=timezone.now() + timedelta(days=7),
        )

        assert invitation.email == "desk.agent@acme.example"
        assert invitation.status == InvitationStatus.PENDING

    @pytest.mark.django_db
    def test_audits_the_creation_under_the_inviters_context(self, inviter, target_role):
        invitation, _ = InvitationService.create(
            inviter=inviter,
            email=INVITEE_EMAIL,
            role=target_role,
            expires_at=timezone.now() + timedelta(days=7),
        )

        entry = AuditLog.objects.get(entity_type="invitation", entity_id=str(invitation.pk))
        assert entry.action == "invitation.created"
        assert entry.actor_id == inviter.user_account_id
        assert entry.tenant_id == inviter.tenant_id

    @pytest.mark.django_db
    def test_rejects_a_role_from_another_tenant(self, inviter):
        foreign_role = Role.objects.create(tenant_id=2, name="front_desk")

        with pytest.raises(InvitationError):
            InvitationService.create(
                inviter=inviter,
                email=INVITEE_EMAIL,
                role=foreign_role,
                expires_at=timezone.now() + timedelta(days=7),
            )

    @pytest.mark.django_db
    def test_requires_the_member_invite_permission(self, target_role):
        # A member whose role lacks member.invite cannot invite.
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(email="viewer@example.com")
        membership = Membership.objects.create(
            tenant_id=1, user_account=user, status=MembershipStatus.ACTIVE
        )
        viewer_role = Role.objects.create(tenant_id=1, name="viewer")
        RolePermission.objects.create(
            role=viewer_role, tenant_id=1, permission_code=Permissions.MEMBER_VIEW
        )
        MembershipRole.objects.create(
            membership=membership, role=viewer_role, tenant_id=1
        )

        with pytest.raises(InsufficientPermission):
            InvitationService.create(
                inviter=membership,
                email=INVITEE_EMAIL,
                role=target_role,
                expires_at=timezone.now() + timedelta(days=7),
            )


class TestResend:
    @pytest.mark.django_db
    def test_rotates_the_token_and_extends_expiry(self, inviter, pending_invite):
        invitation, old_token = pending_invite
        new_expires = timezone.now() + timedelta(days=14)

        refreshed, new_token = InvitationService.resend(
            inviter=inviter, invitation_id=invitation.pk, new_expires_at=new_expires
        )

        assert new_token != old_token
        assert refreshed.token_hash == _sha256(new_token)
        assert refreshed.token_hash != _sha256(old_token)
        assert refreshed.expires_at == new_expires
        # The old token no longer resolves to a pending invitation.
        assert not Invitation.objects.filter(
            token_hash=_sha256(old_token), status=InvitationStatus.PENDING
        ).exists()

    @pytest.mark.django_db
    def test_refuses_to_resend_a_non_pending_invitation(self, inviter, pending_invite):
        invitation, _ = pending_invite
        InvitationService.revoke(inviter=inviter, invitation_id=invitation.pk)

        with pytest.raises(InvitationNotPending):
            InvitationService.resend(
                inviter=inviter,
                invitation_id=invitation.pk,
                new_expires_at=timezone.now() + timedelta(days=7),
            )


class TestRevoke:
    @pytest.mark.django_db
    def test_soft_revokes_and_audits(self, inviter, pending_invite):
        invitation, _ = pending_invite

        revoked = InvitationService.revoke(inviter=inviter, invitation_id=invitation.pk)

        assert revoked.status == InvitationStatus.REVOKED
        assert AuditLog.objects.get(
            entity_type="invitation", entity_id=str(invitation.pk), action="invitation.revoked"
        ).actor_id == inviter.user_account_id

    @pytest.mark.django_db
    def test_refuses_to_revoke_a_non_pending_invitation(self, inviter, pending_invite):
        invitation, _ = pending_invite
        InvitationService.revoke(inviter=inviter, invitation_id=invitation.pk)

        with pytest.raises(InvitationNotPending):
            InvitationService.revoke(inviter=inviter, invitation_id=invitation.pk)

    @pytest.mark.django_db
    def test_requires_the_member_manage_permission(self, pending_invite):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(email="viewer2@example.com")
        membership = Membership.objects.create(
            tenant_id=1, user_account=user, status=MembershipStatus.ACTIVE
        )

        with pytest.raises(InsufficientPermission):
            InvitationService.revoke(
                inviter=membership, invitation_id=pending_invite[0].pk
            )


class TestExpireSweep:
    """The maintenance sweep (Step 6): expired → EXPIRED, per-tenant context."""

    def _make_expired_invite(self, tenant_id, email, now):
        """Create a pending invite, then backdate created_at/expires_at so it is
        past-due while still satisfying ``expires_at > created_at`` (the ORM
        insert-time guard cannot create an already-expired row)."""
        invitation = Invitation.objects.unscoped().create(
            tenant_id=tenant_id,
            email=email,
            token_hash=_sha256(email),
            expires_at=now + timedelta(days=7),
        )
        Invitation.objects.unscoped().filter(pk=invitation.pk).update(
            created_at=now - timedelta(days=8),
            expires_at=now - timedelta(days=1),
        )
        return invitation

    @pytest.mark.django_db
    def test_future_invitations_are_left_untouched(self, pending_invite):
        invitation, _ = pending_invite

        expired = InvitationService.expire_past_due()

        assert expired == 0
        invitation.refresh_from_db()
        assert invitation.status == InvitationStatus.PENDING

    @pytest.mark.django_db
    def test_past_due_invitations_are_expired(self, pending_invite):
        now = timezone.now()
        invitation, _ = pending_invite  # still pending and in the future
        self._make_expired_invite(1, "old@acme.example", now)

        expired = InvitationService.expire_past_due(now=now)

        assert expired == 1
        invitation.refresh_from_db()
        assert invitation.status == InvitationStatus.PENDING
        stale = Invitation.objects.unscoped().get(email="old@acme.example")
        assert stale.status == InvitationStatus.EXPIRED

    @pytest.mark.django_db
    def test_sweep_covers_multiple_tenants_each_under_its_context(
        self, inviter, monkeypatch
    ):
        """The sweep is one run over many tenants — every update must happen
        inside the tenant's own stamped context, so RLS admits each write."""
        now = timezone.now()
        TenantService.provision(
            code="beta", name="Beta", base_currency="NGN", owner_email="beta@example.com"
        )

        from apps.shared import tenancy

        seen = []
        real_run = tenancy.run_as_tenant

        def spy(tenant_id):
            seen.append(tenant_id)
            return real_run(tenant_id)

        # Spy only the sweep itself — provisioning already finished above.
        monkeypatch.setattr(tenancy, "run_as_tenant", spy)

        self._make_expired_invite(1, "old@acme.example", now)
        self._make_expired_invite(2, "old@beta.example", now)

        expired = InvitationService.expire_past_due(now=now)

        assert expired == 2
        assert seen == [1, 2]  # each tenant group ran under its own context
        assert (
            Invitation.objects.unscoped()
            .filter(status=InvitationStatus.EXPIRED)
            .count()
            == 2
        )
