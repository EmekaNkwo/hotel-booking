"""Shared base models — the Django shape of the Shared Kernel (M1.2).

The value objects (apps/shared/value_objects) live framework-free; these
abstract bases are where entities take their first Django shape. Concrete
contexts inherit them so cross-cutting concerns (timestamps, tenancy,
optimistic locking) are defined once and enforced everywhere, instead of being
re-declared (and drifting) on every table.
"""

from django.db import models

from apps.shared.exceptions import ConcurrencyError


def partial_index(
    fields: list[str], condition: models.Q, name: str
) -> models.Index:
    """A conditional (partial) index covering only rows matching ``condition``.

    A full index covers every row; a partial index covers only the hot subset
    (e.g. ``created_at`` for rows where ``status='pending'``), so it stays tiny
    as the table grows — cheaper writes, a cache-hot index, and the same
    speedup for the queries that touch the subset. Declare it in ``Meta.indexes``;
    ``makemigrations`` realizes it as ``CREATE INDEX ... WHERE ...``.

    The *mechanism* is kernel; which subset is hot is context policy.
    """
    return models.Index(name=name, fields=fields, condition=condition)


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


class TenantScopedMixin(models.Model):
    """Abstract base: the tenant that owns every row of the table.

    Ownership is set once at creation (from the authenticated principal, never
    from a request body) and never changes; ``editable=False`` keeps it out of
    forms. The column is stored as a primitive BIGINT; M2 wires it to RLS and
    the tenant-scoping managers, and ``TenantId`` (M1.1) types it at the
    service boundary. ``PositiveBigIntegerField`` enforces non-negativity the
    same way the non-negative ``EntityId`` value object does.
    """

    tenant_id = models.PositiveBigIntegerField(db_index=True, editable=False)

    class Meta:
        abstract = True


class VersionedMixin(models.Model):
    """Abstract base: optimistic-lock protection via a ``version`` counter.

    A plain ``save()`` is last-writer-wins — ``UPDATE ... WHERE id = ?``
    blindly overwrites whatever another writer committed. This mixin overrides
    ``save()`` so every update runs as ONE atomic statement:

        UPDATE ... SET ..., version = <old> + 1
        WHERE id = ? AND version = <as-loaded>

    If another writer changed the row first, the UPDATE matches zero rows and
    ``save()`` raises ``ConcurrencyError`` — a lost update is *detected*
    instead of silently overwritten. The version bump lives in the same
    statement as the check, so no write can slip between them.
    """

    version = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self._state.adding:
            return super().save(*args, **kwargs)
        update_fields = kwargs.pop("update_fields", None)
        using = kwargs.pop("using", None)
        if kwargs.pop("force_update", False):
            # An explicit forced update deliberately skips the version guard.
            return super().save(
                *args, force_update=True, using=using, update_fields=update_fields, **kwargs
            )
        updated = self._conditional_update(update_fields, using)
        if not updated:
            raise ConcurrencyError(
                f"{type(self).__name__} (pk={self.pk}) was changed by another "
                f"writer (expected version {self.version - 1}); reload and retry."
            )

    def _conditional_update(self, update_fields, using):
        # Mirror Django's own update path (Model._save_table): prepare each
        # concrete field's value via pre_save, so auto_now/auto_now_add and
        # field defaults behave exactly as a normal save() would.
        fields = [
            f
            for f in self._meta.local_concrete_fields
            if not f.primary_key and not f.generated
        ]
        if update_fields:
            fields = [
                f for f in fields if f.name in update_fields or f.attname in update_fields
            ]
        values = {f.name: f.pre_save(self, False) for f in fields}
        old_version = self.version
        self.version = old_version + 1
        values["version"] = self.version
        return (
            type(self)
            .objects.using(using)
            .filter(pk=self.pk, version=old_version)
            .update(**values)
        )


class EntityMixin(TimeStampedMixin, TenantScopedMixin, VersionedMixin):
    """Convenience composition: lifecycle + ownership + concurrency, one base.

    Every concrete entity in every bounded context inherits this so identity
    (pk), ownership (tenant_id), lifecycle stamps (created_at/updated_at) and
    concurrency safety (version) are defined once and enforced everywhere —
    the "every context inherits from the same base models" contract.
    """

    class Meta:
        abstract = True
