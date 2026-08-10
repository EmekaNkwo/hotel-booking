"""RLS on the M2.2 tenant-scoped tables — the identity/tenancy spine (M2.4).

The M2.1 migration (0002) established the pattern on the four reliability
tables. This migration extends it to the tables of Identity & Access and
Tenancy: ``membership``, ``role``, ``role_permission``, ``membership_role``,
``invitation``, ``tenant_settings``, ``feature_flag``.

Two flows read *across* tenants before any tenant context exists, which is why
these tables were deferred (M2.2 decision): the middleware resolving a
principal's memberships, and invitation redemption by token. FORCE RLS would
scope those reads to the empty config and break them. This migration closes
the gap with the standard RLS pattern for principal resolution — a pair of
``SECURITY DEFINER`` functions:

- ``app.active_memberships`` — the ONE sanctioned cross-tenant read. It runs
  as the table owner (which bypasses RLS), so the middleware can answer "which
  active tenants does this user belong to?" while every *other* query on
  ``membership`` stays constrained by the policy. It also bakes in the tenant
  status guard: memberships in a non-active (suspended/decommissioned) tenant
  are never resolved.
- ``app.invitation_tenant`` — the one pre-context read redemption needs: from a
  token hash, return the invitation's tenant so the service can then run inside
  that tenant's stamped context.

Both are narrowly parameterized, read-only, and return only facts the caller
already holds (their own memberships / a token they possess) — the security
boundary is "a function can see the rows it was given, nothing else."
"""

from django.db import migrations

# This migration covers ONLY the M2.2 identity & tenancy tables. The four M1
# tables (audit_log, domain_event, outbox_event, idempotency_record) already
# received their policies in shared/0002_enable_rls — re-running them here
# would fail with ``policy already exists`` on a fresh test DB.
TENANT_SCOPED_TABLES = [
    "membership",
    "role",
    "role_permission",
    "membership_role",
    "invitation",
    "tenant_settings",
    "feature_flag",
]

_TENANT_REF = "NULLIF(current_setting('app.tenant_id', true), '')::bigint"

# The principal resolver. SECURITY DEFINER: runs with the owner's privileges
# (the migrating superuser) so it bypasses RLS for exactly this read.
_ACTIVE_MEMBERSHIPS_SQL = """
CREATE OR REPLACE FUNCTION app.active_memberships(p_user_id bigint)
RETURNS TABLE (tenant_id bigint)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT m.tenant_id
    FROM membership m
    JOIN tenant t ON t.id = m.tenant_id
    WHERE m.user_account_id = p_user_id
      AND m.status = 'active'
      AND t.status = 'active'
$$;
"""

# The redemption pre-context lookup: token hash -> the invitation's tenant.
_INVITATION_TENANT_SQL = """
CREATE OR REPLACE FUNCTION app.invitation_tenant(p_token_hash text)
RETURNS bigint
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT tenant_id FROM invitation WHERE token_hash = p_token_hash
$$;
"""


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
        # The SECURITY DEFINER resolvers live in their own schema so their
        # cross-tenant reads are an explicit, sanctioned surface. USAGE to
        # PUBLIC keeps them callable by any role that holds a token or a
        # membership — the authorization is the argument, not the schema.
        cursor.execute("CREATE SCHEMA IF NOT EXISTS app;")
        cursor.execute("GRANT USAGE ON SCHEMA app TO PUBLIC;")
        for table in TENANT_SCOPED_TABLES:
            for statement in _statements(table):
                cursor.execute(statement)
        cursor.execute(_ACTIVE_MEMBERSHIPS_SQL)
        cursor.execute(_INVITATION_TENANT_SQL)


def disable_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_SCOPED_TABLES:
            cursor.execute(f'DROP POLICY IF EXISTS "{table}_tenant_isolation" ON "{table}"')
            cursor.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;')
        cursor.execute("DROP FUNCTION IF EXISTS app.active_memberships(bigint)")
        cursor.execute("DROP FUNCTION IF EXISTS app.invitation_tenant(text)")
        cursor.execute("DROP SCHEMA IF EXISTS app CASCADE;")


class Migration(migrations.Migration):

    dependencies = [
        ("shared", "0002_enable_rls"),
        # The tables must exist before we ALTER/query them.
        ("accounts", "0002_role_membershiprole_invitation_rolepermission"),
        ("tenants", "0001_initial"),
        # tenant_settings and feature_flag are created here — they must exist
        # before this migration can enable RLS on them.
        ("tenants", "0002_tenantsettings_featureflag"),
    ]

    operations = [
        migrations.RunPython(enable_rls, disable_rls),
    ]
