"""Postgres integration tests — CITEXT + GIN(name) (M5, DDS S16).

The unit tier runs on SQLite, where CITEXT and ``USING GIN`` do not exist —
case-insensitive email matching there is guaranteed by the ``Email`` value
object normalizing to lowercase before it ever reaches the database (see
``tests/unit/guests/test_guest_lifecycle.py::TestGuestResolution::
test_resolve_email_is_case_insensitive``). This tier proves the Postgres-only
DB-level backstop itself: the real column type and the real index, applied by
``apps/guests/migrations/0002_citext_primary_email.py`` and
``0003_gin_index_guest_profile_name.py``.

Skipped (not failed) when collected under the SQLite unit settings — mirrors
``tests/integration/test_rls.py``.
"""

import pytest
from django.db import connection

from apps.guests.models import GuestProfile
from apps.guests.services import GuestService
from apps.tenants.models import Tenant

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="CITEXT and GIN indexes are Postgres-only"
)


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(code="acme", name="Acme Hotels", base_currency="NGN")


@pytest.mark.django_db
class TestCitextColumn:
    def test_primary_email_column_is_citext(self, tenant):
        with connection.cursor() as cursor:
            # citext is an extension type, not a SQL-standard builtin, so
            # information_schema.columns.data_type reports it generically as
            # 'USER-DEFINED' — the real type name lives in udt_name.
            cursor.execute(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name = 'guests_guestprofile' AND column_name = 'primary_email'"
            )
            (udt_name,) = cursor.fetchone()
        assert udt_name == "citext"

    def test_db_level_lookup_is_case_insensitive(self, tenant):
        GuestProfile.objects.create(
            tenant=tenant, primary_email="Ada@Example.com", status="active"
        )

        # A raw, case-varied WHERE clause — proves the DB column itself folds
        # case, independent of any application-layer normalization.
        found = GuestProfile.objects.filter(
            tenant=tenant, primary_email="ADA@EXAMPLE.COM"
        ).exists()

        assert found is True

    def test_partial_unique_index_folds_case_on_conflict(self, tenant):
        GuestService.resolve(tenant, email="Ada@Example.com")

        # Same identity, different casing — CITEXT collapses both into one
        # partial-unique-constraint conflict, so resolve() must return the
        # same profile rather than raising IntegrityError to the caller.
        second = GuestService.resolve(tenant, email="ADA@EXAMPLE.COM")
        first = GuestService.resolve(tenant, email="ada@example.com")

        assert second.id == first.id
        assert GuestProfile.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
class TestGinIndex:
    def test_gin_index_exists_on_guest_profile_name(self, tenant):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexdef FROM pg_indexes "
                "WHERE tablename = 'guests_guestprofile' "
                "AND indexname = 'guests_guestprofile_name_gin'"
            )
            row = cursor.fetchone()
        assert row is not None
        assert "gin" in row[0].lower()
