"""Unit tests for AccountService — lockout, deactivation, session flush (M2.4).

Order: failure accounting → threshold lock → retryable window recovery →
deactivation/lock session termination → auth integration → deferred-audit pin.

Sessions are created with the DB SessionStore (the documented way to fabricate
a logged-in cookie) so ``_terminate_sessions`` has something to find.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.utils import timezone

from apps.accounts.models import UserStatus
from apps.accounts.services import AccountService, AuthService

UserAccount = get_user_model()

EMAIL = "lock@acme.example"
PASSWORD = "Good!pw123"


@pytest.fixture
def user():
    return UserAccount.objects.create_user(email=EMAIL, password=PASSWORD)


def _login(email=EMAIL, password=PASSWORD):
    return AuthService.authenticate(email=email, password=password)


def _make_session(user) -> str:
    store = SessionStore()
    store["_auth_user_id"] = str(user.pk)
    store["_auth_user_hash"] = "x"
    store.save()
    return store.session_key


def _lock(user):
    """Drive the account to LOCKED via real failed attempts."""
    for _ in range(settings.AUTH_LOCKOUT_THRESHOLD):
        _login(password="wrong")
    user.refresh_from_db()
    assert user.status == UserStatus.LOCKED


class TestFailureAccounting:
    @pytest.mark.django_db
    def test_failed_attempts_increment_below_threshold(self, user):
        assert _login(password="wrong") is None
        user.refresh_from_db()

        assert user.failed_attempts == 1
        assert user.status == UserStatus.ACTIVE

    @pytest.mark.django_db
    def test_unknown_email_does_not_count(self, user):
        assert _login(email="ghost@acme.example", password="wrong") is None

        user.refresh_from_db()
        assert user.failed_attempts == 0

    @pytest.mark.django_db
    def test_failed_attempts_repeatedly_increment(self, user):
        for _ in range(3):
            assert _login(password="wrong") is None

        user.refresh_from_db()
        assert user.failed_attempts == 3


class TestThresholdLock:
    @pytest.mark.django_db
    def test_threshold_failure_locks_the_account(self, user):
        for _ in range(settings.AUTH_LOCKOUT_THRESHOLD - 1):
            _login(password="wrong")
        user.refresh_from_db()
        assert user.status == UserStatus.ACTIVE

        # The threshold attempt flips the status and stamps locked_at.
        assert _login(password="wrong") is None
        user.refresh_from_db()
        assert user.status == UserStatus.LOCKED
        assert user.locked_at is not None

    @pytest.mark.django_db
    def test_correct_password_within_the_window_stays_rejected(self, user):
        _lock(user)

        assert _login() is None  # right password, but still locked
        user.refresh_from_db()
        assert user.status == UserStatus.LOCKED

    @pytest.mark.django_db
    def test_failure_after_lock_re_stamps_the_window(self, user):
        _lock(user)
        first_stamp = user.locked_at

        assert _login(password="wrong") is None
        user.refresh_from_db()

        assert user.locked_at >= first_stamp


class TestWindowRecovery:
    @pytest.mark.django_db
    def test_lock_clears_after_the_window_with_a_correct_password(self, user):
        _lock(user)
        user.locked_at = timezone.now() - timedelta(
            seconds=settings.AUTH_LOCKOUT_SECONDS + 5
        )
        user.save(update_fields=["locked_at"])

        assert _login() is not None  # window elapsed → retry succeeds
        user.refresh_from_db()
        assert user.status == UserStatus.ACTIVE
        assert user.locked_at is None
        assert user.failed_attempts == 0

    @pytest.mark.django_db
    def test_wrong_password_after_the_window_relocks_fresh(self, user):
        _lock(user)
        user.locked_at = timezone.now() - timedelta(
            seconds=settings.AUTH_LOCKOUT_SECONDS + 5
        )
        user.save(update_fields=["locked_at"])

        assert _login(password="wrong") is None  # a fresh failure burst begins
        user.refresh_from_db()
        assert user.failed_attempts == 1


class TestSessionTermination:
    @pytest.mark.django_db
    def test_deactivate_terminates_the_users_sessions(self, user):
        key = _make_session(user)
        assert Session.objects.filter(session_key=key).exists()

        AccountService.deactivate_account(user, reason="fraud")
        user.refresh_from_db()

        assert user.status == UserStatus.DEACTIVATED
        assert user.deactivated_at is not None
        assert not Session.objects.exists()

    @pytest.mark.django_db
    def test_lock_account_terminates_the_users_sessions(self, user):
        _make_session(user)

        AccountService.lock_account(user, reason="suspicious")

        assert user.status == UserStatus.LOCKED
        assert not Session.objects.exists()


class TestAuthIntegration:
    @pytest.mark.django_db
    def test_successful_login_resets_failed_attempts(self, user):
        for _ in range(3):
            _login(password="wrong")
        user.refresh_from_db()
        assert user.failed_attempts == 3

        assert _login() is not None
        user.refresh_from_db()
        assert user.failed_attempts == 0
        assert user.status == UserStatus.ACTIVE

    @pytest.mark.django_db
    def test_deactivated_account_cannot_authenticate(self, user):
        AccountService.deactivate_account(user, reason="terminated")

        assert _login() is None


class TestDeferredAuditPin:
    @pytest.mark.django_db
    def test_lock_and_deactivation_record_no_audit_row_yet(self, user):
        """Deferred: ``user.status_changed`` audit needs a platform-scoped
        channel (``audit_log`` is tenant-scoped under FORCE-RLS). Pinned so the
        gap is explicit, exactly as redemption's cross-context audit was.
        """
        AccountService.lock_account(user, reason="suspicious")
        AccountService.deactivate_account(user, reason="fraud")

        from apps.shared.models import AuditLog

        assert AuditLog.objects.filter(entity_type="user_account").count() == 0
