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
