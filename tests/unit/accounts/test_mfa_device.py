"""Model tests for ``MfaDevice`` — the M2.5 persistence shape (DDS §1).

These pin the *schema facts* only: platform-scoping (no ``tenant_id``), the
FK lifecycle, the closed ``device_type`` set (E3), the uniqueness and the
lifecycle CHECK, the mutable-stamp conventions, and which fields must never be
user-editable (``secret_key``). TOTP math and Fernet encryption are deliberately
out of scope here — they land in M2.5 Step 3/4.
"""

import pytest
from django.db import IntegrityError, models

from apps.accounts.models import MfaDevice, MfaDeviceType, UserAccount


@pytest.fixture
def user():
    return UserAccount.objects.create_user(email="mfa@acme.example")


def _device(user, **overrides):
    """Create an MfaDevice with a throwaway ciphertext placeholder secret.

    The real secret generation/encryption is Step 3/4; this test only needs a
    non-null ``secret_key`` value to exercise the schema.
    """
    fields = {
        "user_account": user,
        "device_type": MfaDeviceType.TOTP,
        "name": "authenticator",
        "secret_key": "ciphertext-placeholder",
    }
    fields.update(overrides)
    return MfaDevice.objects.create(**fields)


class TestPlatformScoped:
    def test_has_no_tenant_id(self):
        """MfaDevice is person-owned, not tenant-scoped (DDS §1: belongs to
        user_account; UserAccount is platform-global)."""
        field_names = {f.name for f in MfaDevice._meta.fields}
        assert "tenant_id" not in field_names


class TestForeignKey:
    @pytest.mark.django_db
    def test_ons_delete_cascade_removes_device(self, user):
        """A device is part of its owner's life — CASCADE (DDS §1, A.3)."""
        _device(user)
        assert MfaDevice.objects.filter(user_account=user).count() == 1

        user.delete()

        assert MfaDevice.objects.count() == 0

    @pytest.mark.django_db
    def test_two_devices_under_the_same_user(self, user):
        """A user may hold several devices (verified vs pending, second type)."""
        _device(user, name="phone")
        _device(user, name="laptop")

        assert MfaDevice.objects.filter(user_account=user).count() == 2


class TestDeviceTypeClosedSet:
    def test_text_choices(self):
        assert MfaDeviceType.TOTP.value == "totp"
        assert MfaDeviceType.WEBAUTHN.value == "webauthn"

    @pytest.mark.django_db
    def test_check_constraint_rejects_unknown_type(self, user):
        """The DB CHECK (E3) rejects a device_type outside the closed set."""
        with pytest.raises(IntegrityError):
            _device(user, device_type="yubikey")


class TestUniqueness:
    @pytest.mark.django_db
    def test_unique_user_type_name(self, user):
        _device(user, device_type=MfaDeviceType.TOTP, name="phone")

        with pytest.raises(IntegrityError):
            _device(user, device_type=MfaDeviceType.TOTP, name="phone")

    @pytest.mark.django_db
    def test_same_user_different_types_or_names_ok(self, user):
        _device(user, device_type=MfaDeviceType.TOTP, name="phone")
        _device(user, device_type=MfaDeviceType.TOTP, name="laptop")
        _device(user, device_type=MfaDeviceType.WEBAUTHN, name="phone")

        assert MfaDevice.objects.filter(user_account=user).count() == 3


class TestLifecycleConstraint:
    @pytest.mark.django_db
    def test_unverified_and_not_removed_allowed(self, user):
        device = _device(user)
        assert device.verified_at is None
        assert device.removed_at is None

    @pytest.mark.django_db
    def test_verified_allowed_even_if_removed(self, user):
        from django.utils import timezone

        _device(user, verified_at=timezone.now(), removed_at=timezone.now())

    @pytest.mark.django_db
    def test_unverified_and_removed_is_rejected(self, user):
        """DDS §1 CHK (verified_at IS NOT NULL OR removed_at IS NULL): a device
        cannot be BOTH unverified AND removed."""
        from django.utils import timezone

        with pytest.raises(IntegrityError):
            _device(user, removed_at=timezone.now())


class TestMixinConventions:
    @pytest.mark.django_db
    def test_time_stamps_populated(self, user):
        device = _device(user)

        assert device.created_at is not None
        assert device.updated_at is not None

    def test_server_owned_fields_are_not_editable(self):
        """secret_key/verified_at/removed_at are never user input (server-set),
        so they must not surface as editable fields (matches tenant_id etc.)."""
        assert MfaDevice._meta.get_field("secret_key").editable is False
        assert MfaDevice._meta.get_field("verified_at").editable is False
        assert MfaDevice._meta.get_field("removed_at").editable is False

    @pytest.mark.django_db
    def test_secret_key_column_is_char(self, user):
        """The secret column is a bounded CharField (Fernet ciphertext)."""
        field = MfaDevice._meta.get_field("secret_key")
        assert isinstance(field, models.CharField)