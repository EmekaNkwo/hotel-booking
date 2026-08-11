"""Unit tests for the RFC 6238 TOTP primitives (M2.5 step 3).

Fixed timestamps and the RFC's own 8-digit test vectors pin the algorithm
deterministically; the 6-digit default and ±1 verification window are asserted
against the same binary so the production path is proven without a second
external oracle.
"""

import base64
import string

from apps.accounts import totp


# RFC 6238 Appendix B — the SHA1 shared secret is the ASCII bytes of the 20
# digits "12345678901234567890", and the vectors are 8-digit values.
def _rfc_secret_b32() -> str:
    return base64.b32encode(b"12345678901234567890").decode()


RFC_SHA1_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]


class TestGenerateSecret:
    def test_canonical_uppercase_unpadded_base32(self):
        secret = totp.generate_secret()
        assert secret == secret.upper()
        assert "=" not in secret
        assert set(secret) <= set(string.ascii_uppercase + "234567")

    def test_is_160_bits(self):
        secret = totp.generate_secret()
        assert len(secret) == 32  # 160 bits -> exactly 32 base32 chars

    def test_secrets_are_distinct(self):
        assert totp.generate_secret() != totp.generate_secret()


class TestRfc6238Vectors:
    def test_sha1_8_digit_vectors(self):
        """The RFC's own SHA1 vectors (RFC 6238 Appendix B), 8 digits."""
        secret = _rfc_secret_b32()
        for at, expected in RFC_SHA1_VECTORS:
            assert totp.compute_code(secret, at=at, digits=8) == expected, at


class TestComputeCode:
    def test_default_is_6_digits(self):
        secret = _rfc_secret_b32()
        code = totp.compute_code(secret, at=1234567890)
        assert len(code) == 6
        assert code.isdigit()

    def test_six_digit_matches_last_six_of_eight_digit(self):
        """The 6-digit default is the same binary truncated — the last 6 digits
        of the RFC's 8-digit code for the same counter."""
        secret = _rfc_secret_b32()
        assert totp.compute_code(secret, at=1234567890) == "89005924"[-6:]

    def test_advancing_one_period_changes_code(self):
        secret = totp.generate_secret()
        assert totp.compute_code(secret, at=0) != totp.compute_code(secret, at=30)


class TestVerifyCode:
    def test_valid_code_at_same_time(self):
        secret = totp.generate_secret()
        at = 1234567890
        code = totp.compute_code(secret, at=at)
        assert totp.verify_code(secret, code, at=at) is True

    def test_wrong_code_rejected(self):
        secret = totp.generate_secret()
        at = 1234567890
        assert totp.verify_code(secret, "000000", at=at) is False

    def test_wrong_secret_rejected(self):
        code = totp.compute_code(totp.generate_secret(), at=1234567890)
        assert totp.verify_code(totp.generate_secret(), code, at=1234567890) is False

    def test_window_accepts_plus_minus_one_step(self):
        secret = totp.generate_secret()
        at = 1234567890
        code = totp.compute_code(secret, at=at)
        assert totp.verify_code(secret, code, at=at + 30) is True  # +1 step
        assert totp.verify_code(secret, code, at=at - 30) is True  # -1 step

    def test_window_rejects_two_steps_out(self):
        secret = totp.generate_secret()
        at = 1234567890
        code = totp.compute_code(secret, at=at)
        assert totp.verify_code(secret, code, at=at + 60) is False

    def test_zero_window_is_strict(self):
        secret = totp.generate_secret()
        at = 1234567890
        code = totp.compute_code(secret, at=at)
        assert totp.verify_code(secret, code, at=at + 30, window=0) is False

    def test_normalizes_secret_case_and_padding(self):
        """Hand-entered secrets (lowercase, padding stripped) verify identically."""
        canonical = totp.generate_secret()
        sloppy = canonical.lower().rstrip("=")
        at = 1234567890
        code = totp.compute_code(canonical, at=at)
        assert totp.verify_code(sloppy, code, at=at) is True

    def test_strips_surrounding_whitespace_on_code(self):
        secret = totp.generate_secret()
        at = 1234567890
        code = totp.compute_code(secret, at=at)
        assert totp.verify_code(secret, f"  {code}  ", at=at) is True


class TestBuildProvisioningUri:
    def test_otpauth_uri_shape(self):
        secret = totp.generate_secret()
        uri = totp.build_provisioning_uri(secret, label="owner@acme.example", issuer="Hotel")
        assert uri.startswith("otpauth://totp/")
        assert "Hotel:owner%40acme.example" in uri
        assert f"secret={secret}" in uri
        assert "issuer=Hotel" in uri
        assert "algorithm=SHA1" in uri
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_label_is_url_encoded(self):
        uri = totp.build_provisioning_uri(
            "AAAA", label="a b@c", issuer="Hotel"
        )
        assert "Hotel:a%20b%40c" in uri