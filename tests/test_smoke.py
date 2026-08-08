"""M0 smoke tests: prove the project boots and the wiring is sound.

Deliberately database-free — Postgres arrives with the Docker step, so these
tests must pass with no database reachable.
"""

from django.conf import settings


def test_custom_user_model_is_locked():
    """E1 (roadmap): AUTH_USER_MODEL is decided before the first migration."""
    assert settings.AUTH_USER_MODEL == "accounts.UserAccount"


def test_time_zone_is_utc():
    """SDD R2: store UTC; property-local timezones apply at the read edge."""
    assert settings.TIME_ZONE == "UTC"


def test_admin_urlconf_resolves():
    """The root URLconf resolves /admin/ (raises Resolver404 if the route is missing)."""
    from django.urls import resolve

    resolve("/admin/")


def test_celery_app_is_exposed():
    """config/__init__ exposes one Celery app for worker, beat and shell."""
    from config import celery_app

    assert celery_app.main == "hotel_booking"
