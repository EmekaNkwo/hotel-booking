"""Test-only app hosting the M1.2 probe models.

Probe models (StampProbe, StatusProbe, VersionProbe, …) are defined in test
files under ``app_label = "probes"`` so they live in their OWN app — never in
``apps.shared``. This matters now that ``shared`` is a migrated app: Django's
test-database serialization and ``makemigrations`` both iterate *registered*
models, and a probe registered under ``shared`` would make Django expect a
``shared_*`` table (serialization) and a migration (drift check).

``tests.probes`` is deliberately registered ONLY in the test settings and its
migrations are disabled (``MIGRATION_MODULES = {"probes": None}``), so it is
never serialized and never generates migrations.
"""

from django.apps import AppConfig


class ProbesConfig(AppConfig):
    name = "tests.probes"
    verbose_name = "Test probe models"
