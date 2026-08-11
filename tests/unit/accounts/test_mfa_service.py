"""Unit tests for MfaService — the TOTP device lifecycle (M2.5 step 4).

Audit writes land under a tenant context (enrollment is an in-tenant staff
action), so every service call that audits runs inside ``run_as_tenant``.
Crypto behavior is not re-tested here (Step 3 owns it); this suite proves the
*service* contract: lifecycle, encryption-at-rest, authorization, the last-
device guard, audit, atomicity, and idempotency.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts import security, totp
from apps.accounts.exceptions import (
    MfaDeviceNotFound,
    MfaDeviceRemoved,
    MfaDeviceUnverified,
    MfaDuplicateDevice,
    MfaError,
    MfaInvalidCode,
    MfaLastDevice,
)
from apps.accounts.models import MfaDevice, MfaDeviceType
from apps.accounts.services import MfaService
from apps.shared import tenancy
from apps.shared.exceptions import TenantContextMissing
from apps.shared.models import AuditLog
from apps.tenants.services import TenantService

pytestmark = pytest.mark.django_db  # every test here hits the DB

UserAccount = get_user_model()

TENANT = {
    "code": "acme",
    "name": "Acme Hotels",
    "base_currency": "NGN",
    "owner_email": "owner@acme.example",
}


@pytest.fixture
def tenant():
    return TenantService.provision(**TENANT)


@pytest.fixture
def user(tenant):
    return UserAccount.objects.create_user(email="mfa@acme.example", password="pw")


def _plaintext(device) -> str:
    """The TOTP secret, recovered through the Fernet boundary for computing codes."""
    return security.decrypt_secret(device.secret_key)


def _current_code(device) -> str:
    return totp.compute_code(_plaintext(device))


class TestEnroll:
    def test_enrolls_unverified_device_and_returns_uri(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, uri = MfaService.enroll(user=user, name="phone")

        assert device.user_account == user
        assert device.device_type == MfaDeviceType.TOTP
        assert device.name == "phone"
        assert device.verified_at is None
        assert device.removed_at is None
        assert uri.startswith("otpauth://totp/")
        assert f"secret={_plaintext(device)}" in uri  # the URI carries the secret

    def test_secret_is_encrypted_at_rest(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")

        stored = MfaDevice.objects.get(pk=device.pk).secret_key
        plaintext = _plaintext(device)
        assert stored != plaintext
        assert plaintext not in stored
        assert stored.isascii()

    def test_rejects_blank_name(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            with pytest.raises(MfaError):
                MfaService.enroll(user=user, name="   ")

    def test_rejects_unsupported_device_type(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            with pytest.raises(MfaError):
                MfaService.enroll(user=user, name="key", device_type=MfaDeviceType.WEBAUTHN)

    def test_rejects_duplicate_name(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            MfaService.enroll(user=user, name="phone")
            with pytest.raises(MfaDuplicateDevice):
                MfaService.enroll(user=user, name="phone")

    def test_requires_tenant_context_for_audit(self, user):
        """Enrollment audits in the request tenant — failing loud without one."""
        with pytest.raises(TenantContextMissing):
            MfaService.enroll(user=user, name="phone")


class TestVerifyInitial:
    def test_verifies_device_with_correct_code(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))

        device.refresh_from_db()
        assert device.verified_at is not None

    def test_rejects_wrong_code(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            with pytest.raises(MfaInvalidCode):
                MfaService.verify_initial(user=user, device_id=device.pk, code="000000")

    def test_rejects_out_of_window_code(self, tenant, user):
        """A code from 4 steps (2 min) ago is outside the +-1 step window."""
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            secret = _plaintext(device)
            stale = totp.compute_code(secret, at=int(timezone.now().timestamp()) - 120)
            with pytest.raises(MfaInvalidCode):
                MfaService.verify_initial(user=user, device_id=device.pk, code=stale)

    def test_rejects_another_users_device(self, tenant, user):
        other = UserAccount.objects.create_user(email="other@acme.example")
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            with pytest.raises(MfaDeviceNotFound):
                MfaService.verify_initial(user=other, device_id=device.pk, code="000000")

    def test_removed_device_cannot_be_verified(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.remove(user=user, device_id=device.pk)
            device.refresh_from_db()

            with pytest.raises(MfaDeviceRemoved):
                MfaService.verify_initial(
                    user=user, device_id=device.pk, code=_current_code(device)
                )

    def test_reverification_is_idempotent_no_second_audit(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))

        audits = AuditLog.objects.filter(
            entity_type="user", entity_id=str(user.pk), action="mfa.enabled"
        )
        assert audits.count() == 1


class TestVerifyCode:
    def test_accepts_a_verified_device_code(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            assert MfaService.verify_code(user=user, code=_current_code(device)) is True

    def test_rejects_wrong_code(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            assert MfaService.verify_code(user=user, code="000000") is False

    def test_unverified_device_is_not_a_candidate(self, tenant, user):
        """A pending (unverified) device can never authenticate — not a candidate."""
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            assert MfaService.verify_code(user=user, code=_current_code(device)) is False

    def test_removed_device_is_not_a_candidate(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.remove(user=user, device_id=device.pk)
            assert MfaService.verify_code(user=user, code=_current_code(device)) is False

    def test_no_verified_devices_returns_false(self, user):
        assert MfaService.verify_code(user=user, code="000000") is False

    def test_respects_window_via_at(self, tenant, user):
        """An out-of-window code is rejected even when passed the exact timestamp."""
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            at = int(timezone.now().timestamp())
            code = totp.compute_code(_plaintext(device), at=at)
            assert MfaService.verify_code(user=user, code=code, at=at) is True
            assert MfaService.verify_code(user=user, code=code, at=at + 120) is False


class TestRequiresChallenge:
    def test_false_with_no_verified_device(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            MfaService.enroll(user=user, name="phone")
        assert MfaService.requires_challenge(user=user) is False

    def test_true_after_verification(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            assert MfaService.requires_challenge(user=user) is True

    def test_false_after_removal(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.remove(user=user, device_id=device.pk)
            assert MfaService.requires_challenge(user=user) is False


class TestRemove:
    def test_removes_device_and_audits(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.remove(user=user, device_id=device.pk, reason="lost phone")

        device.refresh_from_db()
        assert device.removed_at is not None
        assert AuditLog.objects.filter(
            entity_type="user", entity_id=str(user.pk), action="mfa.removed"
        ).exists()

    def test_cannot_remove_another_users_device(self, tenant, user):
        other = UserAccount.objects.create_user(email="other@acme.example")
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            with pytest.raises(MfaDeviceNotFound):
                MfaService.remove(user=other, device_id=device.pk)

    def test_remove_unknown_device(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            with pytest.raises(MfaDeviceNotFound):
                MfaService.remove(user=user, device_id=9999)

    def test_reremove_is_idempotent_no_second_audit(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.remove(user=user, device_id=device.pk)
            MfaService.remove(user=user, device_id=device.pk)

        audits = AuditLog.objects.filter(
            entity_type="user", entity_id=str(user.pk), action="mfa.removed"
        )
        assert audits.count() == 1

    def test_removing_unverified_device_is_rejected(self, tenant, user):
        """DDS §1: ``removed_at`` may only be set on a verified device."""
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            with pytest.raises(MfaDeviceUnverified):
                MfaService.remove(user=user, device_id=device.pk)

        device.refresh_from_db()
        assert device.removed_at is None


class TestLastDeviceGuard:
    def test_blocks_owner_removing_only_verified_device(self, tenant):
        """SDD §14.1: an active tenant_owner cannot be left without MFA."""
        owner = UserAccount.objects.get(email="owner@acme.example")
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=owner, name="phone")
            MfaService.verify_initial(user=owner, device_id=device.pk, code=_current_code(device))

            with pytest.raises(MfaLastDevice):
                MfaService.remove(user=owner, device_id=device.pk)

            device.refresh_from_db()
            assert device.removed_at is None  # still live

    def test_allows_removal_when_second_verified_device_exists(self, tenant):
        owner = UserAccount.objects.get(email="owner@acme.example")
        with tenancy.run_as_tenant(tenant.pk):
            first, _ = MfaService.enroll(user=owner, name="phone")
            MfaService.verify_initial(user=owner, device_id=first.pk, code=_current_code(first))
            second, _ = MfaService.enroll(user=owner, name="laptop")
            MfaService.verify_initial(user=owner, device_id=second.pk, code=_current_code(second))

            MfaService.remove(user=owner, device_id=first.pk)

            first.refresh_from_db()
            assert first.removed_at is not None

    def test_allows_removal_for_user_without_mfa_required_role(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.remove(user=user, device_id=device.pk)

        device.refresh_from_db()
        assert device.removed_at is not None


class TestAudit:
    def test_enroll_and_verify_and_remove_are_audited(self, tenant, user):
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaService.remove(user=user, device_id=device.pk)

        actions = list(
            AuditLog.objects.filter(entity_type="user", entity_id=str(user.pk))
            .values_list("action", flat=True)
            .order_by("action")
        )
        assert actions == ["mfa.enabled", "mfa.enrolled", "mfa.removed"]


class TestAtomicity:
    def test_enroll_rolls_back_if_audit_fails(self, tenant, user, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("audit service unavailable")

        monkeypatch.setattr("apps.accounts.services.AuditService.record", boom)

        with tenancy.run_as_tenant(tenant.pk):
            with pytest.raises(RuntimeError):
                MfaService.enroll(user=user, name="phone")

        assert MfaDevice.objects.count() == 0  # no orphaned device row


class TestCorruptSecretFailsClosed:
    def test_verify_code_propagates_decryption_error(self, tenant, user):
        """A device whose stored secret cannot be decrypted fails loud — never
        silently treated as a no-match (security posture: fail closed)."""
        with tenancy.run_as_tenant(tenant.pk):
            device, _ = MfaService.enroll(user=user, name="phone")
            MfaService.verify_initial(user=user, device_id=device.pk, code=_current_code(device))
            MfaDevice.objects.filter(pk=device.pk).update(secret_key="corrupted")
            device.refresh_from_db()

            with pytest.raises(security.SecretDecryptionError):
                MfaService.verify_code(user=user, code="000000")