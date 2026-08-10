"""Postgres integration tests — RLS + set_config semantics (M2.1, SDD §13.2).

The unit tier runs on SQLite where RLS and ``set_config`` do not exist; these
tests run the SAME project against a real Postgres (config.settings.integration)
and prove the database-level backstop — the POLICY, not merely the application
layer:

1. ``set_config('app.tenant_id', …, true)`` is transaction-local — discarded
   at commit AND at rollback, so a reused/pooled connection can never carry
   tenant A into tenant B's next transaction.
2. The RLS migrations give EVERY tenant-scoped table (the four M1 tables in
   shared/0002, then the seven M2.2 identity & tenancy tables in
   shared/0003) the intended policy: reads scope by the config (USING),
   writes to another tenant are rejected (WITH CHECK), and an un-stamped
   state fails closed to zero rows without erroring. Each test is
   parametrized over all of them.
3. The M2.4 SECURITY DEFINER resolvers (``app.active_memberships`` and
   ``app.invitation_tenant``) are the single sanctioned cross-tenant reads —
   the middleware's principal lookup and the redemption token→tenant lookup
   both escape RLS, and redemption then re-stamps the invitation's tenant so
   its writes are admitted.
4. The superuser exemption is documented honestly.

The DATABASE_URL role is a superuser, and Postgres does not apply RLS to
superusers (BYPASSRLS), so the enforcement tests impersonate a dedicated
non-superuser role via ``SET ROLE``.

Skipped (not failed) when collected under the SQLite unit settings.
"""

import pytest
from django.db import connection, transaction
from django.db.utils import ProgrammingError

from apps.accounts.middleware import TenantContextMiddleware
from apps.accounts.models import Membership, Role, UserAccount
from apps.shared.models import OutboxEvent
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="RLS and set_config are Postgres-only"
)

PROBE_ROLE = "rls_probe"

# The four M1 tenant-scoped tables covered by shared/0002_enable_rls, with a
# raw INSERT that supplies every NOT NULL column (Django applies its field
# defaults in Python, not as schema defaults). Each has two placeholders:
# an identifying value and the tenant_id.
TENANT_SCOPED_TABLES = {
    "audit_log": {
        "value": "b-42",
        "insert": (
            "INSERT INTO audit_log (entity_type, entity_id, action, reason, "
            "request_id, occurred_at, created_at, tenant_id) "
            "VALUES ('booking', %s, 'confirm', '', '', now(), now(), %s)"
        ),
    },
    "domain_event": {
        "value": "booking.confirmed",
        "insert": (
            "INSERT INTO domain_event (event_id_uuid, event_type, event_version, "
            "aggregate_type, aggregate_id, occurred_at, status, payload, "
            "created_at, tenant_id) "
            "VALUES (gen_random_uuid(), %s, 1, 'booking', '', now(), 'published', "
            "'{}', now(), %s)"
        ),
    },
    "outbox_event": {
        "value": "booking.confirmed",
        "insert": (
            "INSERT INTO outbox_event (event_type, event_version, aggregate_type, "
            "aggregate_id, payload, status, attempts, last_error, tenant_id, "
            "created_at, updated_at) "
            "VALUES (%s, 1, '', '', '{}', 'pending', 0, '', %s, now(), now())"
        ),
    },
    "idempotency_record": {
        "value": "key-42",
        "insert": (
            "INSERT INTO idempotency_record (scope, idempotency_key, request_hash, "
            "status, created_at, updated_at, tenant_id) "
            "VALUES ('booking.confirm', %s, 'hash', 'in_progress', now(), now(), %s)"
        ),
    },
    # ---- M2.2 identity & tenancy tables (shared/0003) ----
    # ``parent_rows`` counts the fixture rows each tenant-7 probe already sees,
    # so the parametrized count assertions stay exact.
    "membership": {
        "value": 2,  # user_account_id — created by rls_parents
        "parent_rows": 1,
        "insert": (
            "INSERT INTO membership (user_account_id, status, version, created_at, "
            "updated_at, tenant_id) "
            "VALUES (%s, 'active', 0, now(), now(), %s)"
        ),
    },
    "role": {
        "value": "probe-role",
        "parent_rows": 1,
        "insert": (
            "INSERT INTO role (name, status, version, created_at, updated_at, tenant_id) "
            "VALUES (%s, 'published', 0, now(), now(), %s)"
        ),
    },
    "role_permission": {
        "value": "probe.permission",
        "insert": (
            "INSERT INTO role_permission (permission_code, role_id, tenant_id) "
            "VALUES (%s, 1, %s)"
        ),
    },
    "membership_role": {
        "value": 1,  # role_id — the rls_parents role in tenant 7
        "insert": (
            "INSERT INTO membership_role (role_id, membership_id, tenant_id) "
            "VALUES (%s, 1, %s)"
        ),
    },
    "invitation": {
        "value": "tok-42",
        "insert": (
            "INSERT INTO invitation (token_hash, email, status, expires_at, version, "
            "created_at, updated_at, tenant_id) "
            "VALUES (%s, 'invitee@example.com', 'pending', now() + interval '1 hour', "
            "0, now(), now(), %s)"
        ),
    },
    "tenant_settings": {
        "value": 7,  # tenant_id doubles as the identifying value (PK is the tenant)
        # The spec convention passes (value, tenant). tenant_id takes the SECOND
        # placeholder, so settings is written FIRST (value lands in the jsonb).
        "insert": (
            "INSERT INTO tenant_settings (settings, tenant_id, version, created_at, "
            "updated_at) "
            "VALUES (jsonb_build_object('probe', %s), %s, 0, now(), now())"
        ),
    },
    "feature_flag": {
        "value": "booking.confirm",
        "insert": (
            "INSERT INTO feature_flag (flag_key, enabled, deleted_at, created_at, "
            "updated_at, tenant_id) "
            "VALUES (%s, false, NULL, now(), now(), %s)"
        ),
    },
}


def _insert_outbox(tenant_id: int) -> None:
    # Inserted as the connection's role (superuser) — bypasses RLS on purpose.
    OutboxEvent.objects.create(event_type="booking.confirmed", tenant_id=tenant_id)


def _drop_probe_role(cursor) -> None:
    """Drop the probe role and everything it owns/grants.

    ``DROP OWNED BY`` clears the rows the role owns (inserted via SET ROLE) and
    its grants; it fails on a missing role, so gate on existence first.
    """
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [PROBE_ROLE])
    if cursor.fetchone():
        cursor.execute(f"DROP OWNED BY {PROBE_ROLE} CASCADE")
    cursor.execute(f"DROP ROLE IF EXISTS {PROBE_ROLE}")


@pytest.fixture(scope="module")
def rls_probe_role(django_db_setup, django_db_blocker):
    """A non-superuser, non-BYPASSRLS role with table grants — so RLS binds.

    ``django_db_setup`` is declared so the test DB exists (and the connection
    is redirected to it) before any GRANT runs — without it the SQL silently
    hits the dev database.
    """
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            # Roles are cluster-global and rows inserted via SET ROLE are
            # owned by the role — clean both before (re)creating it.
            _drop_probe_role(cursor)
            cursor.execute(f"CREATE ROLE {PROBE_ROLE} NOSUPERUSER NOBYPASSRLS")
            cursor.execute(f"GRANT USAGE ON SCHEMA public TO {PROBE_ROLE}")
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                f"IN SCHEMA public TO {PROBE_ROLE}"
            )
            cursor.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {PROBE_ROLE}"
            )
    yield
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            _drop_probe_role(cursor)


@pytest.fixture
def rls_parents(django_db_blocker):
    """The M2.2 FK spine the raw-insert specs reference.

    Created under the superuser (BYPASSRLS) OUTSIDE any request tenant, so the
    rows exist regardless of RLS. Two tenants (7 = probe tenant, 8 = foreign
    tenant) with one membership + one role each; the ``membership``/``role``
    count assertions account for these via each spec's ``parent_rows``.
    """
    with django_db_blocker.unblock():
        UserAccount.objects.create(id=1, email="rls-parent-a@example.com", password="x")
        UserAccount.objects.create(id=2, email="rls-parent-b@example.com", password="x")
        Tenant.objects.create(id=7, code="acme", name="Acme", base_currency="NGN", status="active")
        Tenant.objects.create(id=8, code="beta", name="Beta", base_currency="NGN", status="active")
        Role.objects.create(id=1, tenant_id=7, name="r7", status="published")
        Role.objects.create(id=2, tenant_id=8, name="r8", status="published")
        Membership.objects.create(id=1, tenant_id=7, user_account_id=1, status="active")
        Membership.objects.create(id=2, tenant_id=8, user_account_id=1, status="active")
        # Explicit-id inserts do not advance a table's serial sequence — the
        # raw-SQL specs (which omit id) would then collide on the next value.
        # Bump each sequence past the fixture's rows.
        for table in ("membership", "role", "user_account", "tenant"):
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"(SELECT COALESCE(max(id), 1) FROM {table}))"
                )


class TestSetConfigTransactionLocal:
    """The review requirement: a transaction-local config cannot leak through
    a reused/pooled connection."""

    @pytest.mark.django_db(transaction=True)
    def test_config_is_discarded_at_transaction_end(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', '7', true)")

        # A brand-new transaction on the SAME (reused) connection sees nothing.
        # The GUC placeholder persists as '' after the local value is discarded
        # — the RLS policy's NULLIF guard turns that into NULL (no tenant).
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('app.tenant_id', true)")
                assert cursor.fetchone()[0] != "7"

    @pytest.mark.django_db(transaction=True)
    def test_config_is_discarded_on_rollback(self):
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('app.tenant_id', '7', true)")
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('app.tenant_id', true)")
                assert cursor.fetchone()[0] != "7"

    @pytest.mark.django_db(transaction=True)
    def test_middleware_stamp_uses_the_transaction_local_variant(self):
        # The middleware's actual stamping call, exercised against Postgres.
        middleware = TenantContextMiddleware(get_response=lambda request: None)

        with transaction.atomic():
            middleware._stamp_db(7)
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('app.tenant_id', true)")
                assert cursor.fetchone()[0] == "7"

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('app.tenant_id', true)")
                assert cursor.fetchone()[0] != "7"


class TestRlsEnforcement:
    """The POLICY itself, parametrized over every tenant-scoped M1 table.

    Each test impersonates ``rls_probe`` (non-superuser, no BYPASSRLS), so the
    database — not the application — is the layer under test.
    """

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES.keys())
    @pytest.mark.django_db(transaction=True)
    def test_policy_exists_with_using_and_check(self, rls_probe_role, table):
        # pg_policies exposes the policy's USING (qual) and WITH CHECK clauses.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT qual, with_check FROM pg_policies "
                "WHERE tablename = %s AND policyname = %s",
                [table, f"{table}_tenant_isolation"],
            )
            row = cursor.fetchone()
            assert row is not None, f"no tenant policy on {table}"
            qual, with_check = row
            assert "tenant_id" in qual
            assert "tenant_id" in with_check

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES.keys())
    @pytest.mark.django_db(transaction=True)
    def test_no_config_fails_closed_to_zero_rows(self, rls_probe_role, rls_parents, table):
        spec = TENANT_SCOPED_TABLES[table]
        with connection.cursor() as cursor:
            cursor.execute(spec["insert"], [spec["value"], 7])

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET ROLE {PROBE_ROLE}")
                try:
                    cursor.execute(f'SELECT count(*) FROM "{table}"')
                    assert cursor.fetchone()[0] == 0
                finally:
                    cursor.execute("RESET ROLE")

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES.keys())
    @pytest.mark.django_db(transaction=True)
    def test_scoped_insert_and_read_match_the_config(self, rls_probe_role, rls_parents, table):
        spec = TENANT_SCOPED_TABLES[table]
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET ROLE {PROBE_ROLE}")
                try:
                    cursor.execute("SELECT set_config('app.tenant_id', '7', true)")
                    cursor.execute(spec["insert"], [spec["value"], 7])
                    cursor.execute(f'SELECT count(*) FROM "{table}"')
                    assert cursor.fetchone()[0] == 1 + spec.get("parent_rows", 0)
                finally:
                    cursor.execute("RESET ROLE")

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES.keys())
    @pytest.mark.django_db(transaction=True)
    def test_cross_tenant_insert_is_blocked(self, rls_probe_role, rls_parents, table):
        spec = TENANT_SCOPED_TABLES[table]
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET ROLE {PROBE_ROLE}")
                try:
                    cursor.execute("SELECT set_config('app.tenant_id', '7', true)")
                    cursor.execute(spec["insert"], [spec["value"], 7])  # allowed
                    # WITH CHECK: a row whose tenant differs is rejected. Django
                    # wraps the psycopg error; the savepoint (nested atomic) is
                    # opened BEFORE the failing statement so we survive it.
                    with pytest.raises(ProgrammingError, match="row-level security"):
                        with transaction.atomic():
                            cursor.execute(spec["insert"], [spec["value"], 8])
                    cursor.execute(f'SELECT count(*) FROM "{table}"')
                    assert cursor.fetchone()[0] == 1 + spec.get("parent_rows", 0)
                finally:
                    cursor.execute("RESET ROLE")

    @pytest.mark.django_db(transaction=True)
    def test_a_committed_request_cannot_leak_into_the_next_transaction(
        self, rls_probe_role
    ):
        """The review requirement, end-to-end at the RLS layer.

        Request A stamps tenant 7 and commits. Request B reuses the SAME
        pooled connection without stamping: it must see zero rows — tenant 7's
        row must not leak, and the query must not error on the leftover ''
        GUC placeholder (the NULLIF guard).
        """
        _insert_outbox(tenant_id=7)

        # Request A: a request-wide transaction that stamps tenant 7 and ends.
        with transaction.atomic():
            TenantContextMiddleware(get_response=lambda request: None)._stamp_db(7)

        # Request B: fresh transaction, same connection, no stamp.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET ROLE {PROBE_ROLE}")
                try:
                    cursor.execute("SELECT count(*) FROM outbox_event")
                    assert cursor.fetchone()[0] == 0
                finally:
                    cursor.execute("RESET ROLE")

    @pytest.mark.django_db(transaction=True)
    def test_superuser_is_not_constrained(self, rls_probe_role):
        """The honest RLS trade-off: superusers (BYPASSRLS) are exempt.

        This is why the enforcement tests impersonate a limited role, and why
        the app-layer scoping + middleware are the PRIMARY mechanism (SDD §13.2).
        """
        _insert_outbox(tenant_id=7)
        assert OutboxEvent.objects.count() == 1


class TestPrincipalResolver:
    """M2.4: the SECURITY DEFINER reads are the ONE sanctioned escape hatch.

    Everything else fails closed — the middleware could not do its job with a
    plain query, so it uses a function that Postgres runs with definer rights.
    """

    @pytest.mark.django_db(transaction=True)
    def test_principal_resolution_bypasses_rls_for_the_middleware(
        self, rls_probe_role, rls_parents
    ):
        """The middleware's cross-tenant read works; every other read fails closed."""
        with connection.cursor() as cursor:
            cursor.execute(f"SET ROLE {PROBE_ROLE}")
            try:
                # No config → direct reads fail closed, even for the parent's own row.
                cursor.execute("SELECT count(*) FROM membership")
                assert cursor.fetchone()[0] == 0

                # The sanctioned function resolves the parent's active tenant.
                cursor.execute("SELECT app.active_memberships(%s)", [1])
                assert cursor.fetchone()[0] == 7
            finally:
                cursor.execute("RESET ROLE")

    @pytest.mark.django_db(transaction=True)
    def test_redemption_runs_inside_the_invitation_tenant(self, rls_probe_role, rls_parents):
        """The redemption flow: token→tenant lookup escapes RLS; the writes then
        run inside the invitation's stamped context."""
        with connection.cursor() as cursor:
            # Seed a pending invitation in tenant 7 as the superuser (before SET ROLE).
            cursor.execute(
                "INSERT INTO invitation (token_hash, email, status, expires_at, version, "
                "created_at, updated_at, tenant_id) "
                "VALUES ('tok-42', 'invitee@example.com', 'pending', now() + interval '1 day', "
                "0, now(), now(), 7)"
            )
            cursor.execute(f"SET ROLE {PROBE_ROLE}")
            try:
                # Pre-context: the token→tenant lookup escapes RLS.
                cursor.execute("SELECT app.invitation_tenant(%s)", ["tok-42"])
                assert cursor.fetchone()[0] == 7

                # Post-context: membership + audit writes are admitted by tenant 7.
                # set_config(…, true) is TRANSACTION-local, so the stamp and the
                # writes must share one transaction — exactly the redemption flow.
                with transaction.atomic():
                    cursor.execute("SELECT set_config('app.tenant_id', '7', true)")
                    cursor.execute(
                        "INSERT INTO membership (user_account_id, status, version, created_at, "
                        "updated_at, tenant_id) "
                        "VALUES (2, 'active', 0, now(), now(), 7)"
                    )
                    cursor.execute(
                        "INSERT INTO audit_log (entity_type, entity_id, action, reason, "
                        "request_id, occurred_at, created_at, tenant_id) "
                        "VALUES ('membership', '1', 'invitation.redeemed', '', '', now(), now(), 7)"
                    )
                    # Read-back inside the same stamped transaction: the probe
                    # must SEE the rows it just wrote (USING passes), proving the
                    # writes landed inside tenant 7's context.
                    cursor.execute("SELECT count(*) FROM audit_log WHERE tenant_id = 7")
                    assert cursor.fetchone()[0] == 1
            finally:
                cursor.execute("RESET ROLE")
