"""CITEXT on ``guest_profile.primary_email`` — Postgres-only (DDS S16, M5 roadmap).

Mirrors ``apps/shared/migrations/0002_enable_rls.py``: a vendor-guarded
``RunPython`` layers a Postgres-only enhancement on top of a portable model
field, instead of using ``django.contrib.postgres.fields.CITextField`` as the
Django-visible field type (which has no SQLite equivalent and would break the
unit tier the moment ``migrate`` tries to build the in-memory database).

``primary_email`` stays a plain ``CharField`` in Django's model state on every
backend. On Postgres, this migration extends the extension and converts the
real column to ``citext`` for DB-level case-insensitive comparison/uniqueness
(the partial unique index in 0001 then folds case for free). On SQLite, both
steps no-op — case-insensitivity there is guaranteed by the ``Email`` value
object normalizing to lowercase before anything reaches the database, which
is exercised by the unit tier; the Postgres-only behaviour itself is proven by
the integration tier (mirrors ``tests/integration/test_rls.py``).
"""

from django.contrib.postgres.operations import CITextExtension
from django.db import migrations

_TABLE = "guests_guestprofile"
_COLUMN = "primary_email"


def _to_citext(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE "{_TABLE}" ALTER COLUMN "{_COLUMN}" TYPE CITEXT;')


def _to_varchar(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE "{_TABLE}" ALTER COLUMN "{_COLUMN}" TYPE VARCHAR(254);')


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0001_initial"),
    ]

    operations = [
        # CreateExtension/CITextExtension self-guards on non-Postgres vendors.
        CITextExtension(),
        migrations.RunPython(_to_citext, _to_varchar),
    ]
