"""Recipes — the packaged persistence idioms of the Shared Kernel (M1.2).

Each helper wraps a non-obvious Django/ORM line so every context uses the
mechanism once, correctly, and cannot half-apply it. The *mechanism* is kernel;
the choices, conditions, and field sets are context-owned arguments.
"""

from django.db import models


def partial_index(
    fields: list[str], condition: models.Q, name: str
) -> models.Index:
    """A conditional (partial) index covering only rows matching ``condition``.

    A full index covers every row; a partial index covers only the hot subset
    (e.g. ``created_at`` for rows where ``status='pending'``), so it stays tiny
    as the table grows — cheaper writes, a cache-hot index, and the same
    speedup for the queries that touch the subset. Declare it in ``Meta.indexes``;
    ``makemigrations`` realizes it as ``CREATE INDEX ... WHERE ...``.
    """
    return models.Index(name=name, fields=fields, condition=condition)


def conditional_update(
    queryset: models.QuerySet, conditions: dict[str, object], values: dict[str, object]
) -> int:
    """Run ONE atomic conditional UPDATE over rows matching ``conditions``.

    ``values`` may use ``F()`` expressions (e.g. ``inventory=F("inventory")-1``),
    which are evaluated in the database, never in Python — so a counter bump
    cannot lose a concurrent write the way ``obj.field += 1`` can. Returns the
    number of rows updated: ``0`` means the conditions no longer held (a lost
    race), letting callers detect and retry without a read-then-write window.
    Pair a ``version`` in ``conditions`` with ``version=F("version")+1`` in
    ``values`` for optimistic locking at the queryset level.
    """
    return queryset.filter(**conditions).update(**values)


def status_constraint(
    field: str, choices: type[models.TextChoices], name: str
) -> models.CheckConstraint:
    """A CheckConstraint restricting ``field`` to the closed set ``choices``.

    ``choices=`` alone is form-level only and enforces nothing in the database;
    this constraint is what makes the closed set a schema fact that every writer
    (create, bulk, raw SQL, imports) must respect. The ``name`` is context-owned.
    """
    return models.CheckConstraint(
        condition=models.Q(**{f"{field}__in": choices.values}),
        name=name,
    )
