"""RFC 6238 TOTP primitives for MFA (M2.5 step 3).

The specs (SDD §14.1, DMS §1) name "TOTP" without pinning parameters, so this
module implements the RFC 6238 defaults every authenticator app assumes:
**HMAC-SHA1, 6 digits, 30-second period**, with a one-step clock-drift window
on verification (RFC 6238 §5.2). Stdlib only — no ``pyotp`` dependency.

Representation: secrets are canonical **unpadded uppercase base32** (what a
user scans); decoding tolerates case and missing padding for hand entry.
Ciphertext lives in ``apps.accounts.security`` — this module never sees it.
"""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
import urllib.parse

#: The defaults shared by the otpauth URI and the verifier (RFC 6238).
DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30
#: Time steps accepted either side of the current one (RFC 6238 §5.2).
DEFAULT_WINDOW = 1


def generate_secret() -> str:
    """Return a fresh TOTP shared secret as canonical unpadded uppercase base32.

    160 bits (RFC 6238: the shared secret should be at least this) -> 20 random
    bytes -> exactly 32 base32 characters. The caller shows this to the user and
    stores it (encrypted); it is never logged.
    """
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _base32_decode(secret: str) -> bytes:
    """Decode a TOTP secret into its raw bytes.

    Normalizes the canonical form: strips whitespace, uppercases, and re-adds
    padding so hand-entered values (with or without ``=``) verify identically.
    """
    normalized = re.sub(r"\s+", "", secret).upper()
    padded = normalized + "=" * (-len(normalized) % 8)
    return base64.b32decode(padded)


def _hotp(secret: bytes, counter: int, digits: int = DEFAULT_DIGITS) -> str:
    """HOTP value for ``counter`` via dynamic truncation (RFC 4226 §5.3).

    The counter is the moving factor (``floor(now / period)`` under TOTP). This
    is the low-level primitive the RFC 6238 test vectors exercise directly; the
    public ``compute_code`` layers base32 decoding and the time step on top.
    """
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{binary % (10 ** digits):0{digits}d}"


def compute_code(
    secret: str,
    *,
    at: int | None = None,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
) -> str:
    """TOTP code for ``secret`` at Unix time ``at`` (seconds; defaults to now)."""
    counter = int(time.time() if at is None else at) // period
    return _hotp(_base32_decode(secret), counter, digits)


def verify_code(
    secret: str,
    code: str,
    *,
    at: int | None = None,
    window: int = DEFAULT_WINDOW,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
) -> bool:
    """True when ``code`` matches ``secret`` within a ``window`` of time steps.

    RFC 6238 §5.2: the verifier must allow some clock drift, so candidates at
    ``counter - window .. counter + window`` are compared (constant-time per
    candidate). ``window=0`` is strict. Replay protection is the session
    layer's job (M2.5 step 6) — this function only judges validity "now".
    """
    counter = int(time.time() if at is None else at) // period
    secret_bytes = _base32_decode(secret)
    candidates = [
        _hotp(secret_bytes, c, digits) for c in range(counter - window, counter + window + 1)
    ]
    return any(hmac.compare_digest(expected, code.strip()) for expected in candidates)


def build_provisioning_uri(
    secret: str,
    *,
    label: str,
    issuer: str,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
) -> str:
    """The ``otpauth://`` URI an authenticator scans to enroll (shown once).

    Label is ``issuer:label`` URL-encoded with the issuer repeated as a query
    parameter — the convention Google Authenticator et al. require to display
    the account name. The URI is returned to the user exactly once at
    enrollment and is never stored (DDS §1: no plaintext secret persisted).
    """
    path = urllib.parse.quote(f"{issuer}:{label}", safe=":")
    params = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": digits,
            "period": period,
        }
    )
    return f"otpauth://totp/{path}?{params}"
