"""R0.7/R1.3 regression: config/settings/base.py must fail closed when
DJANGO_SECRET_KEY is unset, never silently boot with an insecure default —
but test.py/integration.py must remain importable in that SAME clean
environment, since their own deterministic secret override must take
effect before base.py's unconditional `env("DJANGO_SECRET_KEY")` call (run
as part of `from .base import *`) ever gets a chance to raise.

Runs in a subprocess with `environ.Env.read_env` patched to a no-op so the
repo's real `.env` (which always provides a real secret for local dev) is
never consulted — this isolates every assertion here to the settings
modules' own fallback behavior, independent of the developer's actual
environment.
"""

import subprocess
import sys

_NO_ENV_FILE = """
import environ
environ.Env.read_env = staticmethod(lambda *a, **k: None)
"""


def _run_in_clean_env(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _NO_ENV_FILE + script],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_base_settings_fail_closed_without_secret_key():
    script = """
import os
os.environ.pop("DJANGO_SECRET_KEY", None)

from django.core.exceptions import ImproperlyConfigured

try:
    import config.settings.base  # noqa: F401
except ImproperlyConfigured:
    print("RAISED_IMPROPERLY_CONFIGURED")
else:
    print("DID_NOT_RAISE")
"""
    result = _run_in_clean_env(script)
    assert "RAISED_IMPROPERLY_CONFIGURED" in result.stdout, (
        f"expected ImproperlyConfigured; stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_prod_settings_fail_closed_without_secret_key():
    script = """
import os
os.environ.pop("DJANGO_SECRET_KEY", None)
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "example.com")

from django.core.exceptions import ImproperlyConfigured

try:
    import config.settings.prod  # noqa: F401
except ImproperlyConfigured:
    print("RAISED_IMPROPERLY_CONFIGURED")
else:
    print("DID_NOT_RAISE")
"""
    result = _run_in_clean_env(script)
    assert "RAISED_IMPROPERLY_CONFIGURED" in result.stdout, (
        f"expected ImproperlyConfigured; stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_test_settings_import_cleanly_without_secret_key_or_env_file():
    """R1.3: the actual regression — this import must NOT raise, even with
    DJANGO_SECRET_KEY absent and no .env file, matching a bare CI runner."""
    script = """
import os
os.environ.pop("DJANGO_SECRET_KEY", None)

import config.settings.test as settings

assert settings.SECRET_KEY == "test-secret-key", settings.SECRET_KEY
print("IMPORTED_OK")
"""
    result = _run_in_clean_env(script)
    assert "IMPORTED_OK" in result.stdout, (
        f"config.settings.test failed to import in a clean environment; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_integration_settings_import_cleanly_without_secret_key_or_env_file():
    script = """
import os
os.environ.pop("DJANGO_SECRET_KEY", None)

import config.settings.integration as settings

assert settings.SECRET_KEY == "integration-test-secret-key", settings.SECRET_KEY
print("IMPORTED_OK")
"""
    result = _run_in_clean_env(script)
    assert "IMPORTED_OK" in result.stdout, (
        f"config.settings.integration failed to import in a clean environment; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_test_settings_do_not_override_a_real_secret_key_from_the_environment():
    """setdefault() must not clobber a genuinely-configured secret — e.g. a
    CI runner that DOES export a real DJANGO_SECRET_KEY for some other
    reason should still see config.settings.test's own deterministic value
    win (test.py sets SECRET_KEY explicitly after the import either way),
    but the setdefault() call itself must not have thrown or misbehaved
    with a real value already present."""
    script = """
import os
os.environ["DJANGO_SECRET_KEY"] = "some-real-externally-provided-secret"

import config.settings.test as settings

assert settings.SECRET_KEY == "test-secret-key", settings.SECRET_KEY
print("IMPORTED_OK")
"""
    result = _run_in_clean_env(script)
    assert "IMPORTED_OK" in result.stdout, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
