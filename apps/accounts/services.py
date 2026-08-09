"""Identity & Access services — invitations and membership redemption (M2.2).

The invitation → redemption flow is the platform's first stateful, idempotent
service transaction:

- The raw token is shown to the inviter exactly once and stored only as a
  sha256 hash — the database never holds the secret.
- Authorization is enforced IN the service layer (SDD §14.2): the inviter's
  membership must carry ``member.invite`` / ``member.manage``, and the tenant
  is derived from that membership — never from a payload.
- Redemption runs PRE-context: the invitee has no membership yet, so the
  invitation is looked up by token (the token is the authorization), guarded by
  status/expiry/email inside ``select_for_update``, and the acceptance
  (membership activation + role grant) is one atomic step. Because the
  redemption happens before a tenant context exists, it writes no audit entry
  yet — ``audit_log`` is RLS-scoped on Postgres and a pre-context write would
  fail closed. The invitation's own audit (creation/revocation) runs under the
  inviter's context and is recorded.
"""

import hashlib
import secrets

from django.db import transaction
from django.utils import timezone

from apps.accounts.exceptions import (
    InsufficientPermission,
    InvitationEmailMismatch,
    InvitationError,
    InvitationExpired,
    InvitationNotFound,
    InvitationNotPending,
)
from apps.accounts.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Role,
)
from apps.accounts.permissions import Permissions
from apps.shared.services.audit import AuditService


class InvitationService:
    """Create, resend, and revoke invitations — under the inviter's context."""

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def create(*, inviter: Membership, email: str, role: Role, expires_at) -> tuple:
        """Create a pending invitation; returns ``(invitation, raw_token)``.

        The tenant is the inviter's (SDD §14.2: derive, never trust). The role
        must belong to that tenant — you cannot invite a user into a role from
        another tenant.
        """
        if not inviter.has_permission(Permissions.MEMBER_INVITE):
            raise InsufficientPermission("the inviter lacks member.invite")
        if role.tenant_id != inviter.tenant_id:
            raise InvitationError("the target role belongs to another tenant")

        token = secrets.token_urlsafe(32)
        with transaction.atomic():
            invitation = Invitation.objects.create(
                tenant_id=inviter.tenant_id,
                email=email.strip().lower(),
                token_hash=InvitationService._hash(token),
                role=role,
                invited_by=inviter.user_account,
                expires_at=expires_at,
            )
            AuditService.record(
                tenant_id=inviter.tenant_id,
                entity_type="invitation",
                entity_id=str(invitation.pk),
                action="invitation.created",
                actor=inviter.user_account,
                reason=f"invited {email.lower()}",
            )
        return invitation, token

    @staticmethod
    def resend(*, inviter: Membership, invitation_id: int, new_expires_at) -> tuple:
        """Rotate the token and extend the window of a pending invitation."""
        if not inviter.has_permission(Permissions.MEMBER_INVITE):
            raise InsufficientPermission("the inviter lacks member.invite")

        token = secrets.token_urlsafe(32)
        with transaction.atomic():
            invitation = Invitation.objects.get(pk=invitation_id, tenant_id=inviter.tenant_id)
            if invitation.status != InvitationStatus.PENDING:
                raise InvitationNotPending(
                    f"invitation {invitation_id} is {invitation.status}, not pending"
                )
            invitation.token_hash = InvitationService._hash(token)
            invitation.expires_at = new_expires_at
            invitation.save()
        return invitation, token

    @staticmethod
    def revoke(*, inviter: Membership, invitation_id: int) -> Invitation:
        """Revoke a pending invitation (soft — the row and its audit survive)."""
        if not inviter.has_permission(Permissions.MEMBER_MANAGE):
            raise InsufficientPermission("the inviter lacks member.manage")

        with transaction.atomic():
            invitation = Invitation.objects.get(pk=invitation_id, tenant_id=inviter.tenant_id)
            if invitation.status != InvitationStatus.PENDING:
                raise InvitationNotPending(
                    f"invitation {invitation_id} is {invitation.status}, not pending"
                )
            invitation.status = InvitationStatus.REVOKED
            invitation.save()
            AuditService.record(
                tenant_id=inviter.tenant_id,
                entity_type="invitation",
                entity_id=str(invitation.pk),
                action="invitation.revoked",
                actor=inviter.user_account,
                reason="revoked by the inviter",
            )
        return invitation


class MembershipService:
    """The grant lifecycle — activated by invitation redemption (pre-context)."""

    @staticmethod
    def redeem_invitation(*, token: str, user) -> Membership:
        """Accept an invitation: activate the grant and assign its role.

        Runs OUTSIDE any tenant context (the invitee is not yet a member). The
        token is the authorization; ``select_for_update`` serializes concurrent
        redemptions of the same invitation so only one can win the guards.
        Idempotent: a user who already holds an ACTIVE grant re-redeems to a
        no-op acceptance rather than an error.
        """
        token_hash = InvitationService._hash(token)

        with transaction.atomic():
            try:
                invitation = (
                    Invitation.objects.unscoped()
                    .select_for_update()
                    .get(token_hash=token_hash)
                )
            except Invitation.DoesNotExist:
                raise InvitationNotFound("no invitation matches this token") from None

            _assert_redeemable(invitation, user)

            existing = (
                Membership.objects.unscoped()
                .filter(tenant_id=invitation.tenant_id, user_account=user)
                .first()
            )
            if existing is not None and existing.status == MembershipStatus.ACTIVE:
                invitation.status = InvitationStatus.ACCEPTED
                invitation.save()
                return existing

            membership, _ = Membership.objects.unscoped().update_or_create(
                tenant_id=invitation.tenant_id,
                user_account=user,
                defaults={"status": MembershipStatus.ACTIVE},
            )
            if invitation.role_id:
                MembershipRole.objects.unscoped().get_or_create(
                    membership=membership,
                    role_id=invitation.role_id,
                    defaults={"tenant_id": invitation.tenant_id},
                )
            invitation.status = InvitationStatus.ACCEPTED
            invitation.save()

        return membership


def _assert_redeemable(invitation: Invitation, user) -> None:
    if invitation.status != InvitationStatus.PENDING:
        raise InvitationNotPending(
            f"invitation {invitation.pk} is {invitation.status}, not pending"
        )
    if invitation.expires_at <= timezone.now():
        raise InvitationExpired(f"invitation {invitation.pk} expired at {invitation.expires_at}")
    if invitation.email.lower() != user.email.lower():
        raise InvitationEmailMismatch(
            "this token belongs to a different email address"
        )
