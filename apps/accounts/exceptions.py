"""Domain exceptions for the invitation → membership flow (M2.2)."""


class InvitationError(Exception):
    """Base for invitation-flow failures."""


class InvitationNotFound(InvitationError):
    """No invitation matches the presented token."""


class InvitationNotPending(InvitationError):
    """The invitation is no longer pending (accepted, revoked, or expired)."""


class InvitationExpired(InvitationError):
    """The invitation is past its expiry window."""


class InvitationEmailMismatch(InvitationError):
    """The redeemer's account email does not match the invitation's."""


class InsufficientPermission(InvitationError):
    """The actor's membership lacks the permission the operation requires."""


class MembershipError(Exception):
    """Base for membership lifecycle failures (M2.4)."""


class MembershipNotActive(MembershipError):
    """The target membership is not an active grant."""


class LastOwnerSelfRevoke(MembershipError):
    """An owner cannot revoke their own grant while they are the tenant's only owner."""


class MfaError(Exception):
    """Base for MFA device lifecycle failures (M2.5 step 4)."""


class MfaDeviceNotFound(MfaError):
    """No device matches the request, or it belongs to another user (object
    ownership is enforced by scoping every lookup to the authenticated user)."""


class MfaDeviceRemoved(MfaError):
    """The device has been soft-removed and can no longer be used or verified."""


class MfaDeviceUnverified(MfaError):
    """The device has not been verified yet and so cannot be removed (DDS §1:
    ``removed_at`` may only be set once ``verified_at`` is non-null)."""


class MfaDuplicateDevice(MfaError):
    """A device with the same (user, device_type, name) already exists."""


class MfaInvalidCode(MfaError):
    """The presented TOTP code is invalid or outside the accepted window."""


class MfaLastDevice(MfaError):
    """Removing this verified device would leave the user with none, while they
    hold a role that requires MFA (SDD §14.1)."""
