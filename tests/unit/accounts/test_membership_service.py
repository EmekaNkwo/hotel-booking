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
    LastOwnerSelfRevoke,
    MembershipNotActive,
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
    def test_redeem_records_the_acceptance_audit(self, invite_for):
        # M2.4: redemption runs inside run_as_tenant, so the acceptance — like
        # every other write in the transaction — lands a same-transaction audit
        # entry under the invitation's tenant, RLS-admitted. (Invitation
        # creation was audited under the inviter's context already.)
        invitation, token = invite_for()
        invitee = UserAccount.objects.create_user(email=INVITEE_EMAIL)

        membership = MembershipService.redeem_invitation(token=token, user=invitee)

        from apps.shared.models import AuditLog

        entry = AuditLog.objects.get(
            entity_type="membership", action="membership.accepted"
        )
        assert entry.entity_id == str(membership.pk)
        assert entry.tenant_id == invitation.tenant_id
        assert entry.actor == invitee

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


class TestRevoke:
    """Membership lifecycle: revoke + audit + last-owner guard (M2.4)."""

    def _member(self, email=INVITEE_EMAIL):
        """Provision acme and add an active member holding ``front_desk``."""
        TenantService.provision(**TENANT)
        invitation, token = _invite_for(email)
        return MembershipService.redeem_invitation(token=token, user=_user(email))

    @pytest.mark.django_db
    def test_revoke_soft_revokes_drops_roles_and_records_audit(self):
        member = self._member()

        owner = Membership.objects.get(user_account__email=TENANT["owner_email"])
        revoked = MembershipService.revoke(actor=owner, membership_id=member.pk, reason="exit")

        assert revoked.status == MembershipStatus.REVOKED
        assert revoked.revoked_at is not None
        assert not revoked.roles.exists()  # role grants cascade off the grant
        from apps.shared.models import AuditLog

        entry = AuditLog.objects.get(entity_type="membership", action="membership.revoked")
        assert entry.entity_id == str(member.pk)
        assert entry.before["status"] == "active"
        assert "front_desk" in entry.before["roles"]
        assert entry.after == {"status": "revoked", "roles": []}

    @pytest.mark.django_db
    def test_revoke_of_a_membership_in_another_tenant_is_not_found(self):
        TenantService.provision(**TENANT)
        TenantService.provision(code="beta", name="Beta", base_currency="NGN", owner_email="b@x.io")
        other = Membership.objects.get(user_account__email="b@x.io")

        owner = Membership.objects.get(user_account__email=TENANT["owner_email"])
        with pytest.raises(Membership.DoesNotExist):
            MembershipService.revoke(actor=owner, membership_id=other.pk)

    @pytest.mark.django_db
    def test_cannot_revoke_own_last_owner_membership(self):
        TenantService.provision(**TENANT)
        owner = Membership.objects.get(user_account__email=TENANT["owner_email"])

        with pytest.raises(LastOwnerSelfRevoke):
            MembershipService.revoke(actor=owner, membership_id=owner.pk)

    @pytest.mark.django_db
    def test_revoking_a_non_active_membership_raises(self):
        member = self._member()
        owner = Membership.objects.get(user_account__email=TENANT["owner_email"])
        MembershipService.revoke(actor=owner, membership_id=member.pk)

        with pytest.raises(MembershipNotActive):
            MembershipService.revoke(actor=owner, membership_id=member.pk)


def _user(email: str) -> UserAccount:
    return UserAccount.objects.create_user(email=email, password="pw")


def _invite_for(email: str):
    inviter = Membership.objects.get(user_account__email=TENANT["owner_email"])
    role, _ = Role.objects.get_or_create(tenant_id=1, name="front_desk")
    invitation, token = InvitationService.create(
        inviter=inviter,
        email=email,
        role=role,
        expires_at=timezone.now() + timedelta(days=7),
    )
    return invitation, token
