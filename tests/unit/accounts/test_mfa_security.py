"""Unit tests for the Fernet secret-at-rest boundary (M2.5 step 3).

Proves the hard invariants: the stored value is ciphertext (never the
plaintext), a different/missing/invalid key fails closed, tampered tokens
fail loudly, and the plaintext secret only ever exists between encrypt and
decrypt in this module.
"""

import base64

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.accounts import security
from apps.accounts.security import SecretDecryptionError

PLAINTEXT = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # a 32-char base32 TOTP secret


def _other_key() -> str:
    return Fernet.generate_key().decode()


class TestRoundTrip:
    def test_encrypt_decrypt_round_trip(self):
        token = security.encrypt_secret(PLAINTEXT)
        assert security.decrypt_secret(token) == PLAINTEXT

    def test_stored_value_is_ciphertext_not_plaintext(self):
        """DDS §1: the stored value differs from, and never contains, the secret."""
        token = security.encrypt_secret(PLAINTEXT)
        assert token != PLAINTEXT
        assert PLAINTEXT not in token
        assert token.isascii()

    def test_same_plaintext_encrypts_differently(self):
        """Fernet randomizes the IV, so two encryptions of one secret differ."""
        assert security.encrypt_secret(PLAINTEXT) != security.encrypt_secret(PLAINTEXT)


class TestFailures:
    def test_wrong_key_cannot_decrypt(self):
        """A stored token is unreadable under a different (rotated) key."""
        token = security.encrypt_secret(PLAINTEXT)
        with override_settings(MFA_FERNET_KEY=_other_key()):
            with pytest.raises(SecretDecryptionError):
                security.decrypt_secret(token)

    def test_tampered_token_rejected(self):
        token = security.encrypt_secret(PLAINTEXT)
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        with pytest.raises(SecretDecryptionError):
            security.decrypt_secret(tampered)

    def test_garbage_token_rejected(self):
        with pytest.raises(SecretDecryptionError):
            security.decrypt_secret("not-a-fernet-token")


class TestFailClosed:
    def test_missing_key_fails_closed_on_encrypt(self):
        with override_settings(MFA_FERNET_KEY=""):
            with pytest.raises(ImproperlyConfigured):
                security.encrypt_secret(PLAINTEXT)

    def test_missing_key_fails_closed_on_decrypt(self):
        token = security.encrypt_secret(PLAINTEXT)
        with override_settings(MFA_FERNET_KEY=""):
            with pytest.raises(ImproperlyConfigured):
                security.decrypt_secret(token)

    def test_non_base64_key_rejected(self):
        with override_settings(MFA_FERNET_KEY="!!!!!"):
            with pytest.raises(ImproperlyConfigured):
                security.get_fernet()

    def test_wrong_length_key_rejected(self):
        """A base64 string that decodes to 16 bytes is not a Fernet key."""
        too_short = base64.urlsafe_b64encode(b"x" * 16).decode()
        with override_settings(MFA_FERNET_KEY=too_short):
            with pytest.raises(ImproperlyConfigured):
                security.get_fernet()


class TestConfiguredKey:
    def test_configured_key_yields_working_fernet(self):
        """The deterministic key in test settings is a valid Fernet key."""
        token = security.encrypt_secret(PLAINTEXT)
        assert security.decrypt_secret(token) == PLAINTEXT