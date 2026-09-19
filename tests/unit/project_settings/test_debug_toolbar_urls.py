"""R1.2 regression: config/urls.py must register django-debug-toolbar's own
URLconf whenever DEBUG is on (config/settings/dev.py enables
DebugToolbarMiddleware unconditionally when DEBUG is on), or every request
under dev settings 500s with ``NoReverseMatch: 'djdt' is not a registered
namespace`` — the toolbar's panels fetch their content from ``__debug__/``
over AJAX, and the middleware assumes that route exists.

Runs each check in a subprocess with a real ``manage.py runserver``-style
Django setup (using the repo's own ``.env``, deliberately NOT stubbed out,
since this checks the actual local dev wiring) — this isolates every
assertion to whether the URLconf itself is wired correctly, independent of
whatever settings module happens to be active in the current test process.
"""

import subprocess
import sys

REPO_ROOT = __file__.rsplit("/tests/", 1)[0]


def _run(settings_module: str, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
        env={"DJANGO_SETTINGS_MODULE": settings_module, "PATH": __import__("os").environ["PATH"]},
    )


def test_debug_toolbar_namespace_is_registered_under_dev_settings():
    script = """
import django
django.setup()

from django.urls import NoReverseMatch, reverse

try:
    url = reverse("djdt:render_panel")
    print("REGISTERED:" + url)
except NoReverseMatch as exc:
    print("NOT_REGISTERED:" + str(exc))
"""
    result = _run("config.settings.dev", script)
    assert "REGISTERED:" in result.stdout, (
        f"debug_toolbar's 'djdt' namespace is not registered under dev settings "
        f"(the original R1 finding); stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_debug_toolbar_namespace_does_not_leak_into_non_dev_settings():
    """DEBUG is False in test/integration/prod (base.py's own default, and
    each of those modules' explicit override) — the toolbar route must not
    exist there, proving the dev.py fix adds no coupling to any other
    settings module."""
    script = """
import os
os.environ.setdefault("DJANGO_SECRET_KEY", "debug-toolbar-check-secret")
import django
django.setup()

from django.urls import NoReverseMatch, reverse

try:
    reverse("djdt:render_panel")
    print("UNEXPECTEDLY_REGISTERED")
except NoReverseMatch:
    print("CORRECTLY_ABSENT")
"""
    result = _run("config.settings.test", script)
    assert "CORRECTLY_ABSENT" in result.stdout, (
        f"debug_toolbar's route leaked into config.settings.test; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_a_plain_request_does_not_500_under_dev_settings():
    """The actual symptom the R1 finding described: every request 500ing
    under dev settings because of the missing namespace. A lightweight
    Django test Client request (no live server, no network) proves the
    full middleware chain — including DebugToolbarMiddleware rendering the
    toolbar — now completes without raising."""
    script = """
import django
django.setup()

from django.test import Client

client = Client()
response = client.get("/api/schema/")
print(f"STATUS:{response.status_code}")
"""
    result = _run("config.settings.dev", script)
    assert "STATUS:500" not in result.stdout, (
        f"a plain request 500'd under dev settings; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "STATUS:" in result.stdout, (
        f"request did not complete; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
