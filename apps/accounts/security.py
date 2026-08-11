"""Fernet boundary for ``MfaDevice.secret_key`` — secret-at-rest (M2.5 step 3).

DDS §1 ``mfa_device``: "stores encrypted secret material only; no plaintext."
This module is the ONLY place a TOTP secret touches cryptography. The Django
model never calls it; ``MfaService`` (step 4) encrypts on enrollment and
decrypts on verification — a plaintext secret never survives past the service
boundary into storage, logs, audit payloads, or responses.

**Fail-closed:** if ``MFA_FERNET_KEY`` is unset or not a base64-encoded 32-byte
key, every call raises ``ImproperlyConfigured``. The system refuses to store or
read a secret rather than degrade to plaintext.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SecretDecryptionError(Exception):
    """A stored secret could not be decrypted (tampering, corruption, or a
    mismatched/rotated key). The plaintext is never recovered in this case."""


def get_fernet() -> Fernet:
    """A Fernet cipher bound to ``MFA_FERNET_KEY``, failing closed on bad config.

    Validated up front: present, base64-decodable, and decoding to exactly 32
    bytes (the Fernet key size). Reading settings per call (not at import) lets
    tests swap keys with ``override_settings`` and keeps a rotated key effective
    without a restart.
    """
    key = settings.MFA_FERNET_KEY.strip()
    if not key:
        raise ImproperlyConfigured(
            "MFA_FERNET_KEY is not set; refusing to operate on TOTP secrets."
        )
    try:
        decoded = base64.urlsafe_b64decode(key.encode("ascii"))
    except ValueError as exc:
        raise ImproperlyConfigured(
            "MFA_FERNET_KEY is not valid base64; expected a Fernet key."
        ) from exc
    if len(decoded) != 32:
        raise ImproperlyConfigured(
            "MFA_FERNET_KEY must decode to exactly 32 bytes (a Fernet key)."
        )
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a TOTP secret for storage; returns the Fernet token as a string.

    The token is never equal to (and never contains) the plaintext.
    """
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt a stored TOTP secret.

    Raises ``SecretDecryptionError`` (never the plaintext, never a leaky
    library exception) on an invalid token, tampering, or a mismatched key.
    """
    try:
        return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "stored TOTP secret could not be decrypted"
        ) from exc
