"""Django project package — settings, URLconf, WSGI/ASGI entrypoints."""

# Django's convention: importing the project exposes the Celery app, so the
# worker, beat, and any tool that imports the package share one instance.
from config.celery import app as celery_app

__all__ = ("celery_app",)
