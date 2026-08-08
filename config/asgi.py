"""ASGI entrypoint — what async servers (Daphne/Uvicorn) import.

Mirror of config.wsgi for the async protocol. Same bootstrap, different
interface: servers call ``application(scope, receive, send)`` on an event
loop. Needed for WebSockets/streaming; sync Django today, async door open.
"""

import os

from django.core.asgi import get_asgi_application

# Same fail-loud default as wsgi.py.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
