"""Identity & Access services — invitations and membership redemption (M2.2).

The invitation → redemption flow is the platform's first stateful, idempotent
service transaction:

- The raw token is shown to the inviter exactly once and stored only as a
  sha256 hash — the database never holds the secret.
- Authorization is enforced IN the service layer (SDD §14.2): the inviter's
  membership must carry ``member.invite`` / ``member.manage``, and the tenant
  is derived from that membership — never from a payload.
- Redemption runs PRE-context: the invitee has no membership yet, so the
  invitation is looked up by token (the token is the authorization) through
  the sanctioned ``app.invitation_tenant`` resolver, and the acceptance
  (membership activation + role grant + acceptance audit) is one atomic step
  running inside ``run_as_tenant`` (M2.4) so every tenant-scoped write —
  including the ``membership.accepted`` audit entry — lands under a context
  that RLS admits. The invitation's own audit (creation/revocation) runs under
  the inviter's context and is recorded.
"""

import hashlib
import secrets

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts import security, totp
from apps.accounts.exceptions import (
    InsufficientPermission,
    InvitationEmailMismatch,
    InvitationError,
    InvitationExpired,
    InvitationNotFound,
    InvitationNotPending,
    LastOwnerSelfRevoke,
    MembershipNotActive,
    MfaDeviceNotFound,
    MfaDeviceRemoved,
    MfaDeviceUnverified,
    MfaDuplicateDevice,
    MfaError,
    MfaInvalidCode,
    MfaLastDevice,
)
from apps.accounts.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    MfaDevice,
    MfaDeviceType,
    Role,
    RolePermission,
    UserAccount,
    UserStatus,
)
from apps.accounts.permissions import Permissions
from apps.shared import tenancy
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

    @staticmethod
    def expire_past_due(*, now=None) -> int:
        """Sweep expired invitations to ``EXPIRED``, one tenant at a time.

        A maintenance sweep has no request membership to authorize it, so it
        reuses the same trusted stamping path as provisioning and redemption:
        each tenant's update runs inside ``run_as_tenant(tenant_id)``, keeping
        app-layer scoping AND the RLS config in force for every write. Uses the
        partial index ``invitation_pending_tenant_exp`` to find candidates.
        Returns the number of invitations expired.
        """
        if now is None:
            now = timezone.now()

        tenant_ids = (
            Invitation.objects.unscoped()
            .filter(status=InvitationStatus.PENDING, expires_at__lte=now)
            .values_list("tenant_id", flat=True)
            .distinct()
        )

        expired = 0
        for tenant_id in tenant_ids:
            with tenancy.run_as_tenant(tenant_id):
                expired += (
                    Invitation.objects.filter(
                        tenant_id=tenant_id,
                        status=InvitationStatus.PENDING,
                        expires_at__lte=now,
                    ).update(status=InvitationStatus.EXPIRED)
                )
        return expired


class MembershipService:
    """The grant lifecycle — activated by invitation redemption (pre-context)."""

    @staticmethod
    def redeem_invitation(*, token: str, user) -> Membership:
        """Accept an invitation: activate the grant and assign its role.

        The invitee is not yet a member, so no request context can exist. The
        token is the authorization: its hash is resolved to a tenant through
        the sanctioned pre-context lookup (``app.invitation_tenant`` under RLS),
        and the ENTIRE redemption — the locked read, the grants, the acceptance
        audit — runs inside ``run_as_tenant`` (M2.4) so every tenant-scoped
        write lands under a context that RLS admits. ``select_for_update``
        serializes concurrent redemptions of the same invitation so only one
        can win the guards. Idempotent: a user who already holds an ACTIVE
        grant re-redeems to a no-op acceptance rather than an error.
        """
        token_hash = InvitationService._hash(token)
        tenant_id = Invitation.objects.lookup_tenant_by_token_hash(token_hash)
        if tenant_id is None:
            raise InvitationNotFound("no invitation matches this token")

        with transaction.atomic():
            with tenancy.run_as_tenant(tenant_id):
                invitation = (
                    Invitation.objects.select_for_update().get(token_hash=token_hash)
                )
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
                AuditService.record(
                    tenant_id=invitation.tenant_id,
                    entity_type="membership",
                    entity_id=str(membership.pk),
                    action="membership.accepted",
                    actor=user,
                    reason=f"redeemed invitation {invitation.pk}",
                )

        return membership

    @staticmethod
    def revoke(*, actor: Membership, membership_id: int, reason: str = "") -> Membership:
        """Soft-revoke an active membership in the actor's tenant.

        Sets ``status=REVOKED`` + ``revoked_at``, drops the membership's role
        grants (they CASCADE from the grant's life), and records a
        same-transaction ``membership.revoked`` audit with before/after
        snapshots. The revoker must hold ``member.manage`` (enforced by the
        view; the service re-checks the tenant match).

        Guard: an owner cannot revoke their OWN membership while they are the
        tenant's last active ``tenant_owner`` — the minimal stand-in for the
        deferred DMS #4 second-approval (a future approval-workflow substrate
        replaces this). Revoking another member's last-owner grant is
        intentionally not guarded here; DMS #4 decides that policy.
        """
        with transaction.atomic():
            target = Membership.objects.unscoped().get(
                pk=membership_id, tenant_id=actor.tenant_id
            )
            if target.status != MembershipStatus.ACTIVE:
                raise MembershipNotActive(
                    f"membership {membership_id} is {target.status}, not active"
                )
            if (
                target.user_account_id == actor.user_account_id
                and _is_last_active_owner(target)
            ):
                raise LastOwnerSelfRevoke(
                    "an owner cannot revoke their own last-owner membership"
                )

            role_names = list(
                target.roles.values_list("role__name", flat=True).order_by("role__name")
            )
            before = {"status": target.status, "roles": role_names}
            target.status = MembershipStatus.REVOKED
            target.revoked_at = timezone.now()
            target.save(update_fields=["status", "revoked_at"])
            target.roles.all().delete()

            AuditService.record(
                tenant_id=actor.tenant_id,
                entity_type="membership",
                entity_id=str(target.pk),
                action="membership.revoked",
                before=before,
                after={"status": MembershipStatus.REVOKED, "roles": []},
                actor=actor.user_account,
                reason=reason,
            )
        return target


def _is_last_active_owner(membership: Membership) -> bool:
    """True when ``membership`` is the tenant's ONLY active ``tenant_owner``."""
    if not membership.roles.filter(role__name="tenant_owner").exists():
        return False
    other_owners = (
        Membership.objects.unscoped()
        .filter(tenant_id=membership.tenant_id, status=MembershipStatus.ACTIVE)
        .exclude(pk=membership.pk)
        .filter(roles__role__name="tenant_owner")
        .distinct()
        .count()
    )
    return other_owners == 0


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


#: Roles whose holders must keep a verified MFA device (SDD §14.1: required for
#: ``tenant_owner``, ``platform_admin``, ``finance``; only ``tenant_owner`` is
#: seeded at M2). The last-device guard consults this; later slices extend it.
MFA_REQUIRED_ROLES: frozenset[str] = frozenset({"tenant_owner"})


def _holds_mfa_required_role(user) -> bool:
    """True when ``user`` holds an MFA-required role in any active tenant.

    Membership is the grant the principal plumbing validates against; the role
    lookup mirrors ``_is_last_active_owner``. If true, removing the user's last
    verified device would leave them unable to use that role — the guard blocks
    it.
    """
    return Membership.objects.unscoped().filter(
        user_account=user,
        status=MembershipStatus.ACTIVE,
        roles__role__name__in=MFA_REQUIRED_ROLES,
    ).exists()


class MfaService:
    """TOTP device lifecycle (DMS §1) — enroll, prove, challenge, remove.

    The service is the ONLY orchestrator of ``MfaDevice``. Crypto stays behind
    the Step 3 boundaries (``totp``/``security``) — nothing here re-implements
    either, and only the Fernet ciphertext is ever persisted (DDS §1). Every
    write is ``transaction.atomic()`` so the row change and its same-transaction
    ``audit_log`` commit or roll back together (M1.5). Every device lookup is
    scoped to the authenticated ``user`` — object ownership is "a device is its
    owner's, and no one else's," and authorization stays on the existing
    authenticated-principal/tenant model (no new mechanism).
    """

    @staticmethod
    def enroll(
        *, user, device_type: str = MfaDeviceType.TOTP, name: str
    ) -> tuple[MfaDevice, str]:
        """Create an unverified TOTP device; returns ``(device, provisioning_uri)``.

        The URI is built from the freshly generated plaintext secret and is the
        ONLY place that secret leaves the process — it is returned once (to be
        shown as a QR code) and never persisted or logged. Only the Fernet
        ciphertext is stored. Enrollment is an in-tenant staff action, so the
        same-transaction audit lands under the request's tenant context
        (``require_current_tenant``).
        """
        tenant_id = tenancy.require_current_tenant()
        name = name.strip()
        if device_type != MfaDeviceType.TOTP:
            raise MfaError("only totp devices can be enrolled at M2.5")
        if not name:
            raise MfaError("device name is required")

        with transaction.atomic():
            if MfaDevice.objects.filter(
                user_account=user, device_type=device_type, name=name
            ).exists():
                raise MfaDuplicateDevice(
                    f"a {device_type} device named {name!r} already exists"
                )

            secret = totp.generate_secret()
            device = MfaDevice.objects.create(
                user_account=user,
                device_type=device_type,
                name=name,
                secret_key=security.encrypt_secret(secret),
            )
            AuditService.record(
                tenant_id=tenant_id,
                entity_type="user",
                entity_id=str(user.pk),
                action="mfa.enrolled",
                actor=user,
                reason=f"enrolled {device_type} device {name!r}",
            )

        uri = totp.build_provisioning_uri(secret, label=user.email, issuer=settings.MFA_ISSUER)
        return device, uri

    @staticmethod
    def verify_initial(*, user, device_id: int, code: str) -> MfaDevice:
        """Prove possession of a freshly enrolled device by entering its code.

        Marks ``verified_at`` on success (single-field update) with a
        same-transaction ``mfa.enabled`` audit. Idempotent: re-verifying an
        already-verified device succeeds without a second audit. A removed
        device can never be verified (DDS §1 lifecycle).
        """
        tenant_id = tenancy.require_current_tenant()
        device = MfaDevice.objects.filter(pk=device_id, user_account=user).first()
        if device is None:
            raise MfaDeviceNotFound(f"no mfa device {device_id} for this user")
        if device.removed_at is not None:
            raise MfaDeviceRemoved(f"device {device_id} has been removed")
        if device.verified_at is not None:
            return device  # idempotent — possession already proven

        if not totp.verify_code(security.decrypt_secret(device.secret_key), code):
            raise MfaInvalidCode("the verification code is invalid or expired")

        with transaction.atomic():
            device.verified_at = timezone.now()
            device.save(update_fields=["verified_at"])
            AuditService.record(
                tenant_id=tenant_id,
                entity_type="user",
                entity_id=str(user.pk),
                action="mfa.enabled",
                actor=user,
                reason=f"verified {device.device_type} device {device.name!r}",
            )
        return device

    @staticmethod
    def verify_code(*, user, code: str, at: int | None = None) -> bool:
        """True when ``code`` matches ANY of the user's verified, live devices.

        Only verified, non-removed devices are candidates (a pending or removed
        device can never authenticate — the MfaDevice lifecycle constraint). A
        pure read with no audit: login attempts are bounded by the boundary's
        throttle, not logged per challenge here.
        """
        devices = list(
            MfaDevice.objects.filter(
                user_account=user,
                verified_at__isnull=False,
                removed_at__isnull=True,
            )
        )
        return any(
            totp.verify_code(security.decrypt_secret(d.secret_key), code, at=at)
            for d in devices
        )

    @staticmethod
    def requires_challenge(*, user) -> bool:
        """True when login must demand a TOTP code (≥1 verified, live device).

        The two-step-login trigger: a user who has enrolled and verified a
        device is challenged on every sign-in; one with none is not.
        """
        return MfaDevice.objects.filter(
            user_account=user,
            verified_at__isnull=False,
            removed_at__isnull=True,
        ).exists()

    @staticmethod
    def remove(*, user, device_id: int, reason: str = "") -> MfaDevice:
        """Soft-remove a device (``removed_at``) with a same-transaction audit.

        Runs under a ``select_for_update`` lock on the owning ``UserAccount``
        row so two concurrent removes cannot both pass the last-device guard.
        Idempotent: removing an already-removed device succeeds as a no-op. The
        guard (``MfaLastDevice``) blocks removing the final verified device
        while the user holds an MFA-required role in an active tenant
        (SDD §14.1) — the minimal v1 stand-in for a future recovery flow.
        """
        with transaction.atomic():
            locked_user = UserAccount.objects.select_for_update().get(pk=user.pk)
            device = MfaDevice.objects.filter(pk=device_id, user_account=locked_user).first()
            if device is None:
                raise MfaDeviceNotFound(f"no mfa device {device_id} for this user")
            if device.removed_at is not None:
                return device  # idempotent
            if device.verified_at is None:
                raise MfaDeviceUnverified(
                    "cannot remove an unverified device (DDS §1: only a verified "
                    "device may be soft-removed)"
                )

            other_verified = MfaDevice.objects.filter(
                user_account=locked_user,
                verified_at__isnull=False,
                removed_at__isnull=True,
            ).exclude(pk=device.pk)
            if not other_verified.exists() and _holds_mfa_required_role(locked_user):
                raise MfaLastDevice(
                    "cannot remove the last verified device while holding an "
                    "MFA-required role"
                )

            device.removed_at = timezone.now()
            device.save(update_fields=["removed_at"])
            AuditService.record(
                tenant_id=tenancy.require_current_tenant(),
                entity_type="user",
                entity_id=str(user.pk),
                action="mfa.removed",
                actor=locked_user,
                reason=reason or f"removed {device.device_type} device {device.name!r}",
            )
        return device


class AccountService:
    """Account lifecycle: login-failure accounting, lockout, deactivation (M2.4).

    ``status`` is the single switch Django's auth backends honor (``is_active``
    is status-derived), so lockout here means "cannot authenticate" everywhere.
    The lock is retryable: after ``AUTH_LOCKOUT_SECONDS`` the next successful
    password check clears it. Deactivation is terminal. Both terminate the
    user's sessions — the same lifecycle write, so there is no window in which
    a locked/deactivated account still holds a valid cookie.
    """

    @staticmethod
    def record_login_failure(email: str) -> None:
        """Increment the failure counter; at the threshold, lock the account.

        Called by ``AuthService.authenticate`` when credentials fail. The
        increment uses ``F()`` (M1.2 step 5) so concurrent failed logins never
        lose a count. Idempotent by design: re-failure on an already-locked
        account just re-stamps ``locked_at``.
        """
        user = UserAccount.objects.filter(email__iexact=email.strip()).first()
        if user is None:
            return  # no such account — nothing to count (and nothing to reveal)

        threshold = settings.AUTH_LOCKOUT_THRESHOLD
        updated = UserAccount.objects.filter(pk=user.pk).update(
            failed_attempts=F("failed_attempts") + 1
        )
        if updated == 0:
            return  # row vanished mid-race; nothing to do

        user.refresh_from_db()
        if user.status == UserStatus.DEACTIVATED:
            return  # terminal state is never re-locked

        if user.failed_attempts >= threshold:
            UserAccount.objects.filter(pk=user.pk).update(
                status=UserStatus.LOCKED, locked_at=timezone.now()
            )

    @staticmethod
    def reset_login_failures(user) -> None:
        """Clear the failure counter; auto-unlock once the lock window elapsed.

        Called by ``AuthService.authenticate`` on success (and by the retryable
        pre-check, which clears an expired lock so the backend can see the
        account again). If the account is still locked because the window
        hasn't elapsed, nothing changes — the counter stays put so a fresh
        burst re-locks immediately.
        """
        lockout_seconds = settings.AUTH_LOCKOUT_SECONDS
        if user.status == UserStatus.LOCKED:
            if user.locked_at is None:
                return  # no stamp → window unknowable → fail closed, stay locked
            elapsed = timezone.now() - user.locked_at
            if elapsed.total_seconds() < lockout_seconds:
                return  # inside the window — stays locked
            # Window elapsed: the lock was a burst guard, not a verdict — clear it.
            UserAccount.objects.filter(pk=user.pk).update(
                status=UserStatus.ACTIVE,
                locked_at=None,
                failed_attempts=0,
            )
            user.status = UserStatus.ACTIVE
            user.locked_at = None
            user.failed_attempts = 0
            return

        UserAccount.objects.filter(pk=user.pk).update(failed_attempts=0)
        user.failed_attempts = 0

    @staticmethod
    def _terminate_sessions(user) -> None:
        """Delete every session whose decoded principal is ``user``.

        Session termination is the lifecycle-relevant half of item 4. Iterating
        decoded session data is the documented way to find a user's sessions
        without a session-store index; the scan is acceptable for M2.4's scale
        and is called only on explicit lock/deactivate.
        """
        for session in Session.objects.all():
            if session.get_decoded().get("_auth_user_id") == str(user.pk):
                session.delete()

    @staticmethod
    def lock_account(user, *, reason: str = "") -> None:
        """Manually lock an account and terminate its sessions."""
        UserAccount.objects.filter(pk=user.pk).update(
            status=UserStatus.LOCKED, locked_at=timezone.now()
        )
        user.status = UserStatus.LOCKED
        user.locked_at = timezone.now()
        AccountService._terminate_sessions(user)

    @staticmethod
    def deactivate_account(user, *, reason: str = "") -> None:
        """Terminally deactivate an account and terminate its sessions."""
        UserAccount.objects.filter(pk=user.pk).update(
            status=UserStatus.DEACTIVATED, deactivated_at=timezone.now()
        )
        user.status = UserStatus.DEACTIVATED
        user.deactivated_at = timezone.now()
        AccountService._terminate_sessions(user)


class AuthService:
    """Authenticate and manage session lifecycle.

    ``authenticate`` is pure — it wraps Django's backend call and returns the
    user (or ``None``); the caller owns the request/session.
    """

    @staticmethod
    def authenticate(*, email: str, password: str):
        """Authenticate by email + password via Django's backends.

        Returns an active ``UserAccount`` or ``None`` on failure. The caller
        should call ``django.contrib.auth.login(request, user)`` after a
        successful return.

        Lockout accounting (M2.4): every failed attempt is counted and, at
        ``AUTH_LOCKOUT_THRESHOLD``, locks the account (``status=locked``);
        every success clears the counter. A lock whose window has elapsed is
        cleared up front so the backend sees an active account again — the
        retryable recovery is: correct password after the window succeeds,
        wrong password counts as a fresh failure.
        """
        from django.contrib.auth import authenticate as _authenticate

        email = email.strip().lower()

        candidate = UserAccount.objects.filter(email=email).first()
        if candidate is not None and candidate.status == UserStatus.LOCKED:
            AccountService.reset_login_failures(candidate)
            candidate.refresh_from_db()

        user = _authenticate(username=email, password=password)
        if user is not None and user.is_active:
            AccountService.reset_login_failures(user)
            return user

        AccountService.record_login_failure(email)
        return None


class RoleService:
    """Create and manage tenant-scoped roles with registry-validated permissions."""

    @staticmethod
    def create(*, tenant_id: int, name: str, permission_codes: list[str]) -> Role:
        """Create a role and attach the given permission codes.

        Every code is validated against the closed registry before any write
        (DDS §1: "permission codes validated against a registry at app layer").
        Unknown codes are rejected immediately — no silent misconfiguration.
        """
        from apps.accounts.permissions import is_valid

        for code in permission_codes:
            if not is_valid(code):
                raise ValueError(f"unknown permission code: {code!r}")
        with transaction.atomic():
            role = Role.objects.create(tenant_id=tenant_id, name=name)
            RolePermission.objects.bulk_create(
                RolePermission(role=role, tenant_id=tenant_id, permission_code=code)
                for code in permission_codes
            )
        return role
