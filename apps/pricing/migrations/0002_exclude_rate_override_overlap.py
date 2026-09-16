"""Non-overlapping RateOverride windows — Postgres-only GiST EXCLUDE (DDS S8, A.9).

DDS requires ``EXCLUDE USING gist (rate_plan_id WITH =, daterange(start_date,
end_date, '[]') WITH &&)`` — one active override window per plan. Two things
make this migration shaped the way it is:

1. ``btree_gist`` is required so the plain equality (``=``) operator on
   ``rate_plan_id`` can sit in the same GiST index as the range ``&&``
   operator (DDS A.9 says so explicitly). ``BtreeGistExtension`` self-guards
   on non-Postgres vendors (inherited from ``CreateExtension``), so it is
   safe to run unconditionally.

2. ``django.contrib.postgres.constraints.ExclusionConstraint`` has **no**
   vendor guard of its own — its ``constraint_sql()`` unconditionally emits
   ``EXCLUDE USING gist (...)``, and SQLite's schema editor would try to fold
   that into a ``CREATE TABLE`` statement and fail with a syntax error. So,
   same shape as ``apps/shared/migrations/0002_enable_rls.py`` and
   ``apps/guests/migrations/0002_citext_primary_email.py``: the vendor check
   lives in a ``RunPython`` wrapper, not in ``Meta.constraints``. Inside that
   guard, this still uses Django's real ``ExclusionConstraint`` +
   ``RangeOperators`` objects (not hand-written DDL) — calling
   ``constraint.create_sql()``/``remove_sql()`` directly against the
   historical model.

``RateService`` enforces the identical inclusive-range overlap rule in
Python, so SQLite unit tests get the same guarantee at the application layer;
this migration is what proves the DB-level backstop on real Postgres
(``tests/integration/test_pricing_postgres.py``).
"""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models

_CONSTRAINT_NAME = "rate_override_no_overlap"


def _build_constraint() -> ExclusionConstraint:
    date_range = models.Func(
        models.F("start_date"),
        models.F("end_date"),
        models.Value("[]"),
        function="daterange",
    )
    return ExclusionConstraint(
        name=_CONSTRAINT_NAME,
        expressions=[
            ("rate_plan", RangeOperators.EQUAL),
            (date_range, RangeOperators.OVERLAPS),
        ],
        condition=models.Q(active=True),
    )


def _add_exclude_constraint(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    RateOverride = apps.get_model("pricing", "RateOverride")
    schema_editor.execute(_build_constraint().create_sql(RateOverride, schema_editor))


def _drop_exclude_constraint(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    RateOverride = apps.get_model("pricing", "RateOverride")
    schema_editor.execute(_build_constraint().remove_sql(RateOverride, schema_editor))


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0001_initial"),
    ]

    operations = [
        # CreateExtension/BtreeGistExtension self-guards on non-Postgres vendors.
        BtreeGistExtension(),
        migrations.RunPython(_add_exclude_constraint, _drop_exclude_constraint),
    ]
