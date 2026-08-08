"""Development settings: live reload, debug toolbar, permissive hosts."""

from .base import *  # noqa: F403,F401

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Debug toolbar must be the FIRST middleware to time every request.
INSTALLED_APPS += ["debug_toolbar"]
MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")

# In Docker the browser's IP isn't 127.0.0.1, so show the toolbar whenever
# DEBUG is on rather than relying on INTERNAL_IPS.
DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": lambda request: DEBUG}
