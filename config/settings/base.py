"""Base settings shared by every environment.

dev/test/prod each do ``from .base import *`` and override only what differs.
Machine-specific values (secrets, URLs) come from the environment (12-factor)
via django-environ, never from this file.
"""

from pathlib import Path

import environ
from corsheaders.defaults import default_headers as CORS_DEFAULT_HEADERS

# config/settings/base.py -> config/settings -> config -> repo root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# Dev convenience: read a .env file if one exists. Prod uses real env vars.
environ.Env.read_env(str(BASE_DIR / ".env"))

# ---- Core security ---------------------------------------------------------
# No insecure fallback: a boot with this var unset is a misconfiguration in
# every environment that doesn't explicitly override it (dev.py relies on
# .env already providing a real value, per .env.example; test.py/
# integration.py set their own explicit non-secret test values below). A
# deploy that mistakenly points DJANGO_SETTINGS_MODULE at this module
# directly must fail loudly, not boot with a known, publicly-visible key.
SECRET_KEY = env("DJANGO_SECRET_KEY")
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
    "corsheaders",  # A0: cross-origin session-cookie requests from the Angular dev server
    "rest_framework",
    "drf_spectacular",
    "django_filters",
    "django.contrib.postgres",  # CITEXT extension/registration (M5, Postgres-only)
]

LOCAL_APPS = [
    "apps.shared",     # Shared Kernel: value objects + cross-cutting infra (M1)
    "apps.accounts",   # Identity & Access: the custom user lives here (E1, M2)
    "apps.tenants",    # Tenancy: the platform-scoped tenant root + lifecycle (M2)
    "apps.properties", # Property: tenant-scoped property hierarchy (M3)
    "apps.rooms",      # Rooms: tenant-scoped room catalog + state machine (M3)
    "apps.policies",   # Policy Engine: versioned business rules as data (M4)
    "apps.guests",     # Guest Profile: identity resolution, consent, GDPR erasure (M5)
    "apps.pricing",    # Pricing: rate plans, overrides, modifiers, PriceBreakdown (M6)
    "apps.availability",  # Availability + Inventory: the anti-oversell core (M7, DDS D2)
    "apps.reservations",  # Reservation Engine: quote -> hold -> convert/expire (M8)
    "apps.bookings",  # Booking: the committed agreement, confirmed from a converted Reservation (M9)
    "apps.allocation",  # Allocation: deterministic physical Room assignment at check-in (M11)
    "apps.housekeeping",  # Housekeeping: clean -> inspect loop after checkout (M12)
    "apps.notifications",  # Notifications: event-driven delivery via the outbox (M13)
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # A0: must sit above CommonMiddleware (django-cors-headers requirement) so
    # CORS headers are added before any other middleware can short-circuit or
    # redirect the response.
    "corsheaders.middleware.CorsMiddleware",
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
    # Enforces the tenant-sensitive MFA boundary for MFA-required roles (M2.5
    # step 7). Runs inside TenantContextMiddleware's transaction (set_config is
    # live) and AFTER tenant resolution (needs request.tenant_id). Raises 403
    # for an authenticated MFA-required principal whose session lacks MFA
    # assurance for the effective tenant.
    "apps.accounts.middleware.MfaEnforcementMiddleware",
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

# ---- CORS / CSRF (A0) --------------------------------------------------------
# The Angular app is a SEPARATE origin from Django (e.g. localhost:4200 vs
# localhost:8000) but authenticates via the SAME session-cookie mechanism as
# every other client (SDD S14.1) — no token auth was introduced. Two distinct
# browser protections must both be satisfied for that to work cross-origin:
#
# 1. CORS: the browser blocks a cross-origin fetch/XHR response from ever
#    reaching JS unless the server explicitly allows the calling origin AND
#    (separately) allows credentialed requests (cookies) for it. Both are
#    required together — CORS_ALLOW_CREDENTIALS=True has no effect if the
#    origin isn't also allow-listed.
# 2. CSRF: unaffected by CORS. Django's CsrfViewMiddleware still requires the
#    csrftoken cookie's value echoed back as an X-CSRFToken header on every
#    unsafe (POST/PUT/PATCH/DELETE) request — CSRF protection is NOT disabled,
#    only widened to trust the Angular dev origin as a legitimate referrer.
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:4200", "http://127.0.0.1:4200"]
)
CORS_ALLOW_CREDENTIALS = True
# django-cors-headers' default allow-list (accept, content-type, x-csrftoken,
# etc.) does not include X-Tenant-Id (A1's tenant-context header, attached by
# the Angular app's tenant interceptor to every tenant-scoped request). Any
# request carrying it is a non-simple CORS request, so without this the
# browser's preflight rejects it outright (net::ERR_FAILED) the moment a
# tenant is selected — found by testing A1 against this real backend, not a
# mock. Extending the default list (not replacing it) keeps every other
# already-relied-upon header (Authorization, X-CSRFToken, ...) allowed too.
CORS_ALLOW_HEADERS = [*CORS_DEFAULT_HEADERS, "x-tenant-id"]

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=["http://localhost:4200", "http://127.0.0.1:4200"]
)
# The Angular HttpClient reads this cookie and echoes it back as the header
# below (Django's own client-side convention — no custom code needed there).
CSRF_COOKIE_HTTPONLY = False
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"

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

# R0.3/R0.4: periodic reconcilers. The request-time guards
# (ReservationService._reject_if_hold_expired, the notifications
# `delivering` reaper) are the AUTHORITATIVE enforcement — these are the
# best-effort background reconciliation for holds/jobs nobody ever
# revisits, so a missed tick is a delay, never a correctness gap. A
# deployment may override or disable this schedule via its own Celery beat
# configuration; defining it here keeps the application's own periodic
# correctness contract in the codebase rather than depending on an
# operator to remember to configure it externally.
CELERY_BEAT_SCHEDULE = {
    "sweep-expired-reservation-holds": {
        "task": "reservations.sweep_expired_holds",
        "schedule": 60.0,
    },
    "reap-stuck-delivering-notifications": {
        "task": "notifications.reap_stuck_delivering",
        "schedule": 60.0,
    },
}

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

# ---- Availability (M7) -------------------------------------------------------
# The sellable window every AvailabilityService.initialize_horizon() call
# opens by default (DDS D5 volume model: "availability slots, not bookings,
# are the scaling unit"). A config value, not a constant buried in the
# service, because ops may need to widen/narrow the sellable horizon per
# deployment without a code change.
AVAILABILITY_HORIZON_DAYS = env.int("AVAILABILITY_HORIZON_DAYS", default=400)

# ---- Reservation (M8) --------------------------------------------------------
# How long a capacity hold survives before the sweep expires it (SDD S10.1
# names 15 min as the example figure). DB-authoritative — no Redis TTL layer
# (M8 ruling: the sweep alone satisfies the correctness invariants).
RESERVATION_HOLD_MINUTES = env.int("RESERVATION_HOLD_MINUTES", default=15)

# ---- Notifications (M13) -----------------------------------------------------
# How many delivery FAILURES a NotificationJob tolerates before it is
# dead-lettered (DB-authoritative; Celery's own retry ceiling is set slightly
# above this so it never gives up first — see apps/notifications/tasks.py).
NOTIFICATION_MAX_RETRIES = env.int("NOTIFICATION_MAX_RETRIES", default=3)

# R0.4: how long a job may sit in `delivering` before the reaper considers
# it abandoned (a worker crashed between TX1 and TX2 — see
# apps/notifications/services.py's module docstring for the transaction
# shape). Long enough that a genuinely in-flight delivery is never
# false-flagged; short enough to recover promptly.
NOTIFICATION_DELIVERING_TIMEOUT_SECONDS = env.int(
    "NOTIFICATION_DELIVERING_TIMEOUT_SECONDS", default=300
)
