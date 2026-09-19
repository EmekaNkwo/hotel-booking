"""Non-overlapping InventoryBlock/ChannelAllocation windows — Postgres-only
GiST EXCLUDE (DDS S7).

Mirrors ``apps/pricing/migrations/0002_exclude_rate_override_overlap.py``
exactly: ``django.contrib.postgres.constraints.ExclusionConstraint`` has no
vendor guard of its own, so both EXCLUDEs are applied inside a
``RunPython`` vendor check rather than ``Meta.constraints`` — declaring them
there would break SQLite's schema editor (it tries to fold ``EXCLUDE USING
gist (...)`` into ``CREATE TABLE`` and fails with a syntax error).

DDS S7: one non-overlapping window **per room-type** for each of
``inventory_block`` and ``channel_allocation`` — ``EXCLUDE USING gist
(room_type_id WITH =, daterange(start_date, end_date, '[]') WITH &&)``. Both
use the SAME inclusive-range convention as ``rate_override`` (S8, A.9), so
``btree_gist`` (already required for the equality operator to share the
GiST index with the range operator) is reused.
"""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models

_INVENTORY_BLOCK_CONSTRAINT = "inventory_block_no_overlap_per_room_type"
_CHANNEL_ALLOCATION_CONSTRAINT = "channel_allocation_no_overlap_per_room_type"


def _date_range_expr() -> models.Func:
    return models.Func(
        models.F("start_date"),
        models.F("end_date"),
        models.Value("[]"),
        function="daterange",
    )


def _inventory_block_constraint() -> ExclusionConstraint:
    return ExclusionConstraint(
        name=_INVENTORY_BLOCK_CONSTRAINT,
        expressions=[
            ("room_type", RangeOperators.EQUAL),
            (_date_range_expr(), RangeOperators.OVERLAPS),
        ],
        condition=~models.Q(status="released"),
    )


def _channel_allocation_constraint() -> ExclusionConstraint:
    return ExclusionConstraint(
        name=_CHANNEL_ALLOCATION_CONSTRAINT,
        expressions=[
            ("room_type", RangeOperators.EQUAL),
            (_date_range_expr(), RangeOperators.OVERLAPS),
        ],
        condition=models.Q(active=True),
    )


def _add_constraints(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    InventoryBlock = apps.get_model("availability", "InventoryBlock")
    ChannelAllocation = apps.get_model("availability", "ChannelAllocation")
    schema_editor.execute(_inventory_block_constraint().create_sql(InventoryBlock, schema_editor))
    schema_editor.execute(
        _channel_allocation_constraint().create_sql(ChannelAllocation, schema_editor)
    )


def _drop_constraints(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    InventoryBlock = apps.get_model("availability", "InventoryBlock")
    ChannelAllocation = apps.get_model("availability", "ChannelAllocation")
    schema_editor.execute(_inventory_block_constraint().remove_sql(InventoryBlock, schema_editor))
    schema_editor.execute(
        _channel_allocation_constraint().remove_sql(ChannelAllocation, schema_editor)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("availability", "0001_initial"),
    ]

    operations = [
        BtreeGistExtension(),
        migrations.RunPython(_add_constraints, _drop_constraints),
    ]
