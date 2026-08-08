"""Email — a normalized address, as a value object.

The bug this prevents: ``John@Example.com`` and ``john@example.com`` are the
same mailbox, but to a system that stores raw strings they are two different
people — two accounts, two guest profiles, two booking histories for one human.
``Email`` normalizes at the boundary: whatever casing or padding arrives, only
the canonical (stripped, lowercased) form is ever stored, so identity
comparisons everywhere compare canonical values.

Validation boundary (structural only): an email is invalid when it lacks a
single ``@``, a non-empty local part, or a domain with a dot on both sides.
Which domains are *allowed*, whether the mailbox *exists*, or whether the
address is *already registered* are business rules for later contexts
(Policy, a verification service, Accounts/Guests) — not invariants here.
"""

from dataclasses import dataclass

from apps.shared.value_objects.exceptions import InvalidEmail


def _is_valid_email(address: str) -> bool:
    if " " in address:
        return False
    if address.count("@") != 1:
        return False
    local, _, domain = address.partition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    dot_index = domain.index(".")
    # A dot at the edge means no TLD (or no domain name) — not a real address.
    return dot_index not in (0, len(domain) - 1)


@dataclass(frozen=True, slots=True)
class Email:
    """A canonical email address. The stored form is normalized."""
    address: str

    def __post_init__(self) -> None:
        if not isinstance(self.address, str):
            raise InvalidEmail(f"Email must be a string, got {self.address!r}.")
        normalized = self.address.strip().lower()
        if not _is_valid_email(normalized):
            raise InvalidEmail(f"Invalid email address: {self.address!r}.")
        # The one deliberate frozen exception: rewrite to the canonical form
        # before the object escapes construction.
        object.__setattr__(self, "address", normalized)

    def __str__(self) -> str:
        return self.address
