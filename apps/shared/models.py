"""Shared base models — the Django shape of the Shared Kernel (M1.2).

The value objects (apps/shared/value_objects) live framework-free; these
abstract bases are where entities take their first Django shape. Concrete
contexts inherit them so cross-cutting concerns (timestamps, tenancy,
optimistic locking) are defined once and enforced everywhere, instead of being
re-declared (and drifting) on every table.
"""

from django.db import models


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
