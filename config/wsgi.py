"""WSGI entrypoint — what sync servers (gunicorn) import.

The server reads the ``WSGI_APPLICATION`` setting, imports this module, and
calls ``application(environ, start_response)`` for every request. ``runserver``
also uses this internally.
"""

import os

from django.core.wsgi import get_wsgi_application

# Server-imported entrypoints default to PROD so a missing env var fails loud
# (missing SECRET_KEY) instead of silently booting dev settings in prod.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_wsgi_application()
