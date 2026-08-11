"""Base settings shared by every environment.

dev/test/prod each do ``from .base import *`` and override only what differs.
Machine-specific values (secrets, URLs) come from the environment (12-factor)
via django-environ, never from this file.
"""

from pathlib import Path

import environ

# config/settings/base.py -> config/settings -> config -> repo root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# Dev convenience: read a .env file if one exists. Prod uses real env vars.
environ.Env.read_env(str(BASE_DIR / ".env"))

# ---- Core security ---------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-not-for-production")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# ---- Applications -----------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
    "django_filters",
]

LOCAL_APPS = [
    "apps.shared",     # Shared Kernel: value objects + cross-cutting infra (M1)
    "apps.accounts",   # Identity & Access: the custom user lives here (E1, M2)
    "apps.tenants",    # Tenancy: the platform-scoped tenant root + lifecycle (M2)
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Resolves the principal's tenant context once per request and stamps
    # set_config('app.tenant_id', …, true) (SDD §13.2 layer 1, DR-01). Runs
    # AFTER auth (needs request.user), BEFORE any app logic that queries
    # tenant-scoped data. It wraps the request in one transaction so the
    # transaction-local config is stable and can never leak across a pooled
    # connection (M2.1).
    "apps.accounts.middleware.TenantContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---- Authentication ---------------------------------------------------------
# E1 (roadmap): lock the custom user model BEFORE the first migration. This is
# a placeholder; the real model (AbstractBaseUser + email login + MFA) lands in
# M2 while the database is still empty. "accounts" is the app LABEL, not the
# package path "apps.accounts".
AUTH_USER_MODEL = "accounts.UserAccount"

# Failed-login lockout (M2.4). After AUTH_LOCKOUT_THRESHOLD consecutive failed
# attempts the account is LOCKED; the lock auto-clears once AUTH_LOCKOUT_SECONDS
# have elapsed since locked_at (see AccountService.record_login_failure /
# reset_login_failures). Session throttle on top of this lands in M2.4 step 5.
AUTH_LOCKOUT_THRESHOLD = 5
AUTH_LOCKOUT_SECONDS = 900
# Per-IP burst limit on the session-login endpoint (brute-force guard at the
# app boundary; gateway-level limiting is an edge concern). Read per request so
# tests can shrink it with override_settings.
AUTH_LOGIN_THROTTLE_RATE = env("AUTH_LOGIN_THROTTLE_RATE", default="20/min")

# ---- MFA (M2.5) -----------------------------------------------------------
# Fernet key (base64, 32 bytes) encrypting TOTP secrets at rest (DDS §1
# mfa_device: "stores encrypted secret material only; no plaintext"). Empty by
# default; the MFA encryption module fails closed on use if it is unset or
# invalid. Test/dev/integration settings (and .env for dev) provide a real key.
MFA_FERNET_KEY = env("MFA_FERNET_KEY", default="")

# Half-authenticated session window after a successful password but before the
# MFA code completes login (SDD §14.1, two-step login). Bounded short so a
# half-logged-in session cannot be left open.
MFA_PENDING_TIMEOUT_SECONDS = env.int("MFA_PENDING_TIMEOUT_SECONDS", default=600)

# Display name used as the "issuer" in the otpauth provisioning URI an
# authenticator app shows the user when they scan a TOTP QR code.
MFA_ISSUER = env("MFA_ISSUER", default="Hotel Booking")

# Brute-force bound for the second-factor completion endpoint (step 6). The
# user is anonymous during the MFA-pending window, so this keys on IP; tighter
# than the password throttle because a TOTP code is only 10^6 values.
AUTH_MFA_THROTTLE_RATE = env("AUTH_MFA_THROTTLE_RATE", default="10/min")

# ---- Database ---------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://postgres:postgres@localhost:5432/hotel_booking",
    ),
}
# Reuse connections between requests (perf win in prod). Tests override.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

# Every request runs in one database transaction (defense-in-depth; M1
# transactions discipline). TenantContextMiddleware already wraps the full
# request (middleware + view) in transaction.atomic() so its transaction-local
# set_config('app.tenant_id', …, true) is stable and can't leak across a
# pooled connection; ATOMIC_REQUESTS additionally wraps the view callback as a
# nested savepoint so a view can never accidentally commit partial work even
# if the middleware ordering ever changes. Long-running read paths that need
# to escape per-request atomicity opt out explicitly (non_atomic_requests).
ATOMIC_REQUESTS = True

# ---- Cache (Redis) ------------------------------------------------------------
# Django ships a Redis cache backend since 4.0 — no third-party package needed.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
    },
}

# ---- Celery ---------------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/1")
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = "UTC"
CELERY_TASK_TRACK_STARTED = True

# ---- Django REST Framework --------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # M2.3: session auth only — the TenantContextMiddleware resolves the
    # principal from the session cookie BEFORE the view runs, so every
    # tenant-scoped request gets a resolved context without DRF needing to
    # re-authenticate. Token-based auth is deferred (it would require the
    # middleware to also resolve from an Authorization header).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Hospitality Management Platform API",
    "DESCRIPTION": "Modular Django monolith backend.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---- Internationalization -----------------------------------------------------------
LANGUAGE_CODE = "en-us"
# Store UTC; property-local timezones are applied at the read edge (SDD R2).
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---- Static / media ------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---- Passwords / defaults -------------------------------------------------------------
# Argon2id first (SDD §14.1) — the cost factor is tuned to ~100ms of hashing
# time; tests override to MD5 for speed.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# BIGINT identity everywhere (DDS A.1) — no 32-bit serial exhaustion.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
