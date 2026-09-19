"""Postgres integration-tier settings.

The unit tier runs on in-memory SQLite (fast, hermetic) and cannot represent
Postgres-only behavior — RLS, ``set_config`` semantics, CITEXT. This tier runs
the SAME project against a real Postgres (``DATABASE_URL``, e.g. the dev
docker-compose instance) and is where those behaviors are proven.

Select it explicitly — the default ``config.settings.test`` stays SQLite:

    DJANGO_SETTINGS_MODULE=config.settings.integration pytest tests/integration

Migrations apply for real here — that is precisely what the tier verifies
(the RLS migration, the regex constraints, the partial indexes).
"""

import os

# R1.3: same reasoning as config/settings/test.py — base.py's unconditional
# `SECRET_KEY = env("DJANGO_SECRET_KEY")` must not crash this import in a
# clean environment before this file's own deterministic override applies.
os.environ.setdefault("DJANGO_SECRET_KEY", "integration-test-secret-key")

from .base import *  # noqa: F403,F401,E402

DEBUG = False
SECRET_KEY = "integration-test-secret-key"
ALLOWED_HOSTS = ["testserver"]

# MFA (M2.5): a deterministic Fernet key, matching the unit tier.
MFA_FERNET_KEY = "bd1D_roplO5-kqaxbeZvpkOSkkumz5Uf_rOQSjhnWlQ="
# Disable MFA enforcement for integration tests — they run as the owner
# and are not interactive, so they cannot complete the MFA challenge.
MFA_ENFORCEMENT_DISABLED = True

# No Redis/broker dependence; in-memory cache, eager Celery.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Fast hashing (same speed trade-off as the unit tier).
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# The probe models stay in their own non-migrated app so they cannot drift the
# migrated apps — exactly as in the unit tier.
INSTALLED_APPS = [*INSTALLED_APPS, "tests.probes"]
MIGRATION_MODULES = {"probes": None}
