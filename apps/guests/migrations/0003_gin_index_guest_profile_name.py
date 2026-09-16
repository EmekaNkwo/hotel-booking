"""GIN index on ``guest_profile.name`` — Postgres-only, admin search (DDS SC.3).

Applied as raw, vendor-guarded SQL (same shape as
``apps/shared/migrations/0002_enable_rls.py``) rather than
``django.contrib.postgres.indexes.GinIndex`` in ``Meta.indexes``: Django's
``GinIndex.create_sql`` emits ``USING gin`` unconditionally regardless of
backend, so declaring it on the model would break ``migrate`` on the SQLite
unit tier the moment the in-memory test database is built. Keeping it out of
Django's index state also keeps ``makemigrations --check`` quiet on every
backend.
"""

from django.db import migrations

_INDEX = "guests_guestprofile_name_gin"
_TABLE = "guests_guestprofile"


def _create_gin_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'CREATE INDEX "{_INDEX}" ON "{_TABLE}" USING GIN ("name");')


def _drop_gin_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'DROP INDEX IF EXISTS "{_INDEX}";')


class Migration(migrations.Migration):

    dependencies = [
        ("guests", "0002_citext_primary_email"),
    ]

    operations = [
        migrations.RunPython(_create_gin_index, _drop_gin_index),
    ]
