"""Shared base models — the Django shape of the Shared Kernel (M1.2).

The value objects (apps/shared/value_objects) live framework-free; these
abstract bases are where entities take their first Django shape. Concrete
contexts inherit them so cross-cutting concerns (timestamps, tenancy,
optimistic locking) are defined once and enforced everywhere, instead of being
re-declared (and drifting) on every table.
"""

from django.db import models


def status_constraint(
    field: str, choices: type[models.TextChoices], name: str
) -> models.CheckConstraint:
    """A CheckConstraint restricting ``field`` to the closed set ``choices``.

    The E3 recipe's one non-obvious line, packaged so every status column shares
    the mechanism: ``choices=`` alone is form-level only and enforces nothing in
    the database — this constraint is what makes the closed set a schema fact
    that every writer (create, bulk, raw SQL, imports) must respect.
    The ``choices`` class (the allowed set) and ``name`` are context-owned.
    """
    return models.CheckConstraint(
        condition=models.Q(**{f"{field}__in": choices.values}),
        name=name,
    )


class TimeStampedMixin(models.Model):
    """Abstract base: ``created_at``/``updated_at`` lifecycle stamps in UTC.

    ``created_at`` is set once at INSERT and is never editable; ``updated_at``
    refreshes on every ``save()``. Together they give every entity audit-able
    stamps (SDD R2: store UTC; local display happens at the read edge).

    Caveat: ``QuerySet.update()`` bypasses ``save()`` and does not refresh
    ``updated_at`` — bulk paths must set it explicitly with ``F()``.
    """

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    class Meta:
        abstract = True
