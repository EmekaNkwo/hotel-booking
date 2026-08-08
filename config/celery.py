"""Celery application bootstrap.

The worker is its own process, so it needs its own entrypoint. It reuses the
same bootstrap mechanism as every other entry: set DJANGO_SETTINGS_MODULE, then
let Django configure. ``manage.py`` and the worker default to dev because they
are developer-run; deployments override with the real env var.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("hotel_booking")

# Read every CELERY_* setting from Django's settings object, lazily.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Import <app>.tasks for every installed app so tasks register with this app.
app.autodiscover_tasks()
