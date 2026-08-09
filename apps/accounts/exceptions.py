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
