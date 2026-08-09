"""Unit tests for the real ``UserAccount`` custom user model (M2.1, E1, FR-AUTH-01).

Order follows the M1 convention:
creation/normalization → authentication (login) → lifecycle/status →
constraints at the DB layer → optimistic locking → edge cases.
Email is the username (DMS invariant #1): unique platform-wide, normalized to
lowercase at the manager boundary (CITEXT arrives with the Postgres tier).
"""

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError, transaction

from apps.accounts.models import UserStatus
from apps.shared.exceptions import ConcurrencyError

UserAccount = get_user_model()


@pytest.fixture(autouse=True)
def _clean():
    yield
    UserAccount.objects.all().delete()


class TestCreation:
    @pytest.mark.django_db
    def test_create_user_stores_the_email(self):
        user = UserAccount.objects.create_user(email="desk@example.com", password="s3cret")

        assert user.email == "desk@example.com"
        assert user.is_staff is False
        assert user.is_superuser is False
        assert user.status == UserStatus.ACTIVE

    @pytest.mark.django_db
    def test_email_is_normalized_to_lowercase(self):
        # DMS invariant #1: two spellings of one inbox are one account.
        user = UserAccount.objects.create_user(email="Desk@Example.COM", password="x")

        assert user.email == "desk@example.com"

    @pytest.mark.django_db
    def test_create_user_requires_an_email(self):
        with pytest.raises(ValueError):
            UserAccount.objects.create_user(email="", password="x")

    @pytest.mark.django_db
    def test_create_superuser_flags_staff_and_superuser(self):
        user = UserAccount.objects.create_superuser(email="root@example.com", password="x")

        assert user.is_staff is True
        assert user.is_superuser is True


class TestAuthentication:
    @pytest.mark.django_db
    def test_authenticate_succeeds_with_email_and_password(self):
        UserAccount.objects.create_user(email="desk@example.com", password="correct horse")
        user = authenticate(username="desk@example.com", password="correct horse")

        assert user is not None
        assert user.email == "desk@example.com"

    @pytest.mark.django_db
    def test_authenticate_ignores_case_in_the_email(self):
        UserAccount.objects.create_user(email="desk@example.com", password="pw")
        user = authenticate(username="DESK@example.com", password="pw")

        assert user is not None

    @pytest.mark.django_db
    def test_wrong_password_fails(self):
        UserAccount.objects.create_user(email="desk@example.com", password="right")
        assert authenticate(username="desk@example.com", password="wrong") is None

    @pytest.mark.django_db
    def test_duplicate_email_is_blocked_at_the_database(self):
        UserAccount.objects.create_user(email="desk@example.com", password="a")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                UserAccount.objects.create_user(email="desk@example.com", password="b")


class TestStatus:
    @pytest.mark.django_db
    def test_locked_user_cannot_authenticate(self):
        # Django's ModelBackend checks is_active, which derives from status —
        # one switch locks an account for every auth path.
        user = UserAccount.objects.create_user(email="desk@example.com", password="pw")
        user.status = UserStatus.LOCKED
        user.save()

        assert user.is_active is False
        assert authenticate(username="desk@example.com", password="pw") is None

    @pytest.mark.django_db
    def test_status_change_bumps_version(self):
        user = UserAccount.objects.create_user(email="desk@example.com", password="pw")
        user.status = UserStatus.LOCKED
        user.save()

        assert user.version == 1

    @pytest.mark.django_db
    def test_stale_save_raises_concurrency_error(self):
        user = UserAccount.objects.create_user(email="desk@example.com", password="pw")
        desk_a = UserAccount.objects.get(pk=user.pk)
        desk_b = UserAccount.objects.get(pk=user.pk)

        desk_a.status = UserStatus.LOCKED
        desk_a.save()

        desk_b.status = UserStatus.DEACTIVATED
        with pytest.raises(ConcurrencyError):
            desk_b.save()


class TestConstraints:
    @pytest.mark.django_db
    def test_invalid_status_is_blocked_at_the_database(self):
        user = UserAccount.objects.create_user(email="desk@example.com", password="pw")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                UserAccount.objects.filter(pk=user.pk).update(status="half-open")

    @pytest.mark.django_db
    def test_negative_failed_attempts_is_blocked(self):
        user = UserAccount.objects.create_user(email="desk@example.com", password="pw")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                UserAccount.objects.filter(pk=user.pk).update(failed_attempts=-1)

    @pytest.mark.django_db
    def test_user_name_field_is_email(self):
        assert UserAccount.USERNAME_FIELD == "email"
        assert UserAccount.REQUIRED_FIELDS == []
