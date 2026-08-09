"""RLS on the first tenant-scoped tables — the pattern every later context copies.

This migration is the database-level backstop of the defense-in-depth stack
(SDD §13.2 layer 3, DDS A.2): each tenant-scoped reliability table gets
``ENABLE + FORCE ROW LEVEL SECURITY`` and a policy that admits a row only when
its ``tenant_id`` equals ``current_setting('app.tenant_id')``.

The policy uses ``NULLIF(current_setting('app.tenant_id', true), '')`` so every
un-stamped state yields NULL and therefore zero rows — fail-closed without
raising, so maintenance tooling stays alive while a row can never leak. The
NULLIF guard is required, not cosmetic: once a request sets the GUC locally,
the placeholder persists on the pooled connection as ``''`` after commit, and
``''::bigint`` raises ``invalid input syntax``. ``NULLIF`` turns that poisoned
state back into NULL (zero rows). ``TenantContextMiddleware`` stamps the config
inside a request-wide transaction, so it is always set for request-scoped
queries.

Vendor gate: the unit tier runs on SQLite (no RLS); this migration is a no-op
there and is exercised by the Postgres integration tier. Later contexts copy
this file and extend ``TENANT_SCOPED_TABLES`` with their own tables.
"""

from django.db import migrations

TENANT_SCOPED_TABLES = [
    "audit_log",
    "domain_event",
    "outbox_event",
    "idempotency_record",
]

_TENANT_REF = "NULLIF(current_setting('app.tenant_id', true), '')::bigint"


def _statements(table: str) -> list[str]:
    policy = f"{table}_tenant_isolation"
    return [
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;',
        f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;',
        f"CREATE POLICY {policy} ON \"{table}\" "
        f"USING (tenant_id = {_TENANT_REF}) "
        f"WITH CHECK (tenant_id = {_TENANT_REF});",
    ]


def enable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_SCOPED_TABLES:
            for statement in _statements(table):
                cursor.execute(statement)


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_SCOPED_TABLES:
            cursor.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')


class Migration(migrations.Migration):

    dependencies = [
        ("shared", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(enable_rls, disable_rls),
    ]
