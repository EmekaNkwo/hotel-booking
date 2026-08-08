"""Test settings: deterministic, hermetic, fast.

Selected via DJANGO_SETTINGS_MODULE (set in pyproject's [tool.pytest.ini_options]).
"""

from .base import *  # noqa: F403,F401

DEBUG = False
SECRET_KEY = "test-secret-key"
ALLOWED_HOSTS = ["testserver"]  # Django's test client presents this host.

# Tests must not depend on Redis; use an in-memory cache.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

# Run Celery tasks synchronously so tests never need a broker.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Fast hashing for test passwords (argon2's cost would slow the suite down).
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Model tests run against in-memory SQLite so the suite stays hermetic and
# fast — no Postgres/Docker required for unit-level model tests. Postgres-only
# behavior (RLS, range types) gets a dedicated integration tier from M2 on.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
