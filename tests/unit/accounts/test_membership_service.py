"""Unit tests for membership redemption — the invitation acceptance flow (M2.2).

Order: happy path (activate + grant + accept) → token single-use → idempotent
re-entry → guards (not found / expired / email mismatch / non-pending) → the
partial-unique invariant under re-redeem.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.exceptions import (
    InvitationEmailMismatch,
    InvitationExpired,
    InvitationNotFound,
    InvitationNotPending,
)
from apps.accounts.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipStatus,
    Role,
)
from apps.accounts.services import InvitationService, MembershipService
from apps.tenants.services import TenantService

UserAccount = get_user_model()

TENANT = {
    "code": "acme",
    "name": "Acme Hotels",
    "base_currency": "NGN",
    "owner_email": "owner@acme.example",
}
INVITEE_EMAIL = "agent@acme.example"


@pytest.fixture
def invite_for(scope="function"):
    """Return a helper that provisions a tenant and creates an invitation."""

    def _make(email: str = INVITEE_EMAIL):
        TenantService.provision(**TENANT)
        inviter = Membership.objects.get(tenant_id=1)
        role, _ = Role.objects.get_or_create(tenant_id=1, name="front_desk")
        invitation, token = InvitationService.create(
            inviter=inviter,
            email=email,
            role=role,
            expires_at=timezone.now() + timedelta(days=7),
        )
        return invitation, token

    return _make


class TestHappyPath:
    @pytest.mark.django_db
    def test_redeem_activates_the_membership_and_grants_the_role(self, invite_for):
        invitation, token = invite_for()
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)

        membership = MembershipService.redeem_invitation(token=token, user=invitee)

        assert membership.tenant_id == invitation.tenant_id
        assert membership.user_account == invitee
        assert membership.status == MembershipStatus.ACTIVE
        assert membership.roles.get().role.name == "front_desk"
        assert Invitation.objects.get(pk=invitation.pk).status == InvitationStatus.ACCEPTED

    @pytest.mark.django_db
    def test_redeem_writes_no_audit_entry_yet(self, invite_for):
        # Pre-context flow: the invitee has no tenant context, and audit_log is
        # RLS-scoped on Postgres — a pre-context write would fail closed. The
        # acceptance is deliberately audit-silent until the auth-API slice
        # provides a post-redemption context. (Creation was audited already.)
        invitation, token = invite_for()
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)
        MembershipService.redeem_invitation(token=token, user=invitee)

        from apps.shared.models import AuditLog

        assert not AuditLog.objects.filter(entity_type="invitation").exclude(
            action="invitation.created"
        ).exists()

    @pytest.mark.django_db
    def test_redeem_returns_the_existing_membership_for_an_already_active_member(
        self, invite_for
    ):
        # The owner is already an ACTIVE member — redemption is a no-op accept.
        invitation, token = invite_for(email=TENANT["owner_email"])
        owner = UserAccount.objects.get(email=TENANT["owner_email"])

        membership = MembershipService.redeem_invitation(token=token, user=owner)

        assert Membership.objects.count() == 1  # no duplicate grant
        assert membership.user_account == owner
        assert Invitation.objects.get(pk=invitation.pk).status == InvitationStatus.ACCEPTED


class TestTokenSingleUse:
    @pytest.mark.django_db
    def test_a_used_token_cannot_redeem_again(self, invite_for):
        invitation, token = invite_for()
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)
        MembershipService.redeem_invitation(token=token, user=invitee)

        with pytest.raises(InvitationNotPending):
            MembershipService.redeem_invitation(token=token, user=invitee)


class TestGuards:
    @pytest.mark.django_db
    def test_unknown_token_is_not_found(self):
        with pytest.raises(InvitationNotFound):
            MembershipService.redeem_invitation(token="garbage", user=None)

    @pytest.mark.django_db
    def test_expired_invitation_is_rejected(self, invite_for):
        invitation, token = invite_for()
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)
        # Make it old-but-consistently-expired without tripping the
        # expires_at > created_at constraint.
        Invitation.objects.filter(pk=invitation.pk).update(
            created_at=timezone.now() - timedelta(days=30),
            expires_at=timezone.now() - timedelta(days=1),
        )

        with pytest.raises(InvitationExpired):
            MembershipService.redeem_invitation(token=token, user=invitee)

    @pytest.mark.django_db
    def test_email_mismatch_is_rejected(self, invite_for):
        _, token = invite_for(email="someone-else@acme.example")
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)

        with pytest.raises(InvitationEmailMismatch):
            MembershipService.redeem_invitation(token=token, user=invitee)

    @pytest.mark.django_db
    def test_revoked_invitation_is_rejected(self, invite_for):
        invitation, token = invite_for()
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)
        inviter = Membership.objects.get(tenant_id=1)
        InvitationService.revoke(inviter=inviter, invitation_id=invitation.pk)

        with pytest.raises(InvitationNotPending):
            MembershipService.redeem_invitation(token=token, user=invitee)


class TestInvariant:
    @pytest.mark.django_db
    def test_two_invitations_to_the_same_user_cannot_create_two_active_grants(
        self, invite_for
    ):
        # The partial unique index (tenant, user) WHERE active still holds when
        # two different invitations are redeemed for the same user+tenant.
        _, first_token = invite_for()
        _, second_token = invite_for()
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)

        first = MembershipService.redeem_invitation(token=first_token, user=invitee)
        second = MembershipService.redeem_invitation(token=second_token, user=invitee)

        assert second.pk == first.pk  # the second redeem found the active grant
        assert Membership.objects.filter(
            tenant_id=1, user_account=invitee, status=MembershipStatus.ACTIVE
        ).count() == 1
