"""Postgres integration tests — RLS + set_config semantics (M2.1, SDD §13.2).

The unit tier runs on SQLite where RLS and ``set_config`` do not exist; these
tests run the SAME project against a real Postgres (config.settings.integration)
and prove the database-level backstop — the POLICY, not merely the application
layer:

1. ``set_config('app.tenant_id', …, true)`` is transaction-local — discarded
   at commit AND at rollback, so a reused/pooled connection can never carry
   tenant A into tenant B's next transaction.
2. The RLS migration gives EVERY tenant-scoped M1 table the intended policy:
   reads scope by the config (USING), writes to another tenant are rejected
   (WITH CHECK), and an un-stamped state fails closed to zero rows without
   erroring. Each test is parametrized over all four tables — audit_log,
   domain_event, outbox_event, idempotency_record.
3. The superuser exemption is documented honestly.

The DATABASE_URL role is a superuser, and Postgres does not apply RLS to
superusers (BYPASSRLS), so the enforcement tests impersonate a dedicated
non-superuser role via ``SET ROLE``.

Skipped (not failed) when collected under the SQLite unit settings.
"""

import pytest
from django.db import connection, transaction
from django.db.utils import ProgrammingError

from apps.accounts.middleware import TenantContextMiddleware
from apps.shared.models import OutboxEvent

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
    def test_no_config_fails_closed_to_zero_rows(self, rls_probe_role, table):
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
    def test_scoped_insert_and_read_match_the_config(self, rls_probe_role, table):
        spec = TENANT_SCOPED_TABLES[table]
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f"SET ROLE {PROBE_ROLE}")
                try:
                    cursor.execute("SELECT set_config('app.tenant_id', '7', true)")
                    cursor.execute(spec["insert"], [spec["value"], 7])
                    cursor.execute(f'SELECT count(*) FROM "{table}"')
                    assert cursor.fetchone()[0] == 1
                finally:
                    cursor.execute("RESET ROLE")

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES.keys())
    @pytest.mark.django_db(transaction=True)
    def test_cross_tenant_insert_is_blocked(self, rls_probe_role, table):
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
                    assert cursor.fetchone()[0] == 1
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
