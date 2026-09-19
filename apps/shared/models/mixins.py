"""Abstract base mixins — the entity shape of the Shared Kernel (M1.2).

Concrete contexts inherit these so cross-cutting concerns (lifecycle stamps,
tenancy, optimistic locking, append-only logs) are defined once and enforced
everywhere, instead of being re-declared (and drifting) on every table.
"""

from django.db import models

from apps.shared.exceptions import AppendOnlyViolation, ConcurrencyError
from apps.shared.workflows.context import is_workflow_active


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
    service boundary.
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


class AppendOnlyQuerySet(models.QuerySet):
    """QuerySet that refuses mutation — the ORM layer of append-only logs.

    The database trigger/RLS layer (M2) is the schema-level guarantee; this is
    defense-in-depth layer 1 so even ORM code cannot edit or delete a log row.
    """

    def update(self, **kwargs):
        raise AppendOnlyViolation(
            f"{self.model.__name__} is append-only; rows cannot be updated."
        )

    def delete(self):
        raise AppendOnlyViolation(
            f"{self.model.__name__} is append-only; rows cannot be deleted."
        )


class AppendOnlyMixin(models.Model):
    """Abstract base for immutable, append-only logs (domain_event, audit_log).

    Rows are created once and never updated or deleted: the ORM refuses both
    at the model and QuerySet levels. ``created_at`` marks when the record was
    appended; the business timestamp (``occurred_at``) is a separate field on
    the concrete model.
    """

    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyViolation(
                f"{type(self).__name__} is append-only; existing rows cannot be updated."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyViolation(
            f"{type(self).__name__} is append-only; rows cannot be deleted."
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


class WorkflowStateGuardMixin(models.Model):
    """Abstract base: rejects a ``save()`` that changes
    ``workflow_guarded_field`` outside an active ``WorkflowRunner``
    transition (R0.6 red-team finding).

    ``apps.rooms.models.Room`` has enforced exactly this on
    ``operational_state`` since M3 — every ``WorkflowRunner.run()`` call
    already wraps its ``instance.save()`` in ``WorkflowContext()``
    (``apps/shared/workflows/runner.py``), which is generic, not
    Room-specific, so this mixin only generalizes Room's own already-proven
    save() override rather than inventing a new mechanism. Without it, a
    future bulk-update, admin action, or bugfix touching a WorkflowRunner-
    governed status field (e.g. ``BookingLine.objects.filter(...).update(
    status=...)`` or ``obj.status = X; obj.save()``) silently bypasses the
    declared state machine, the audit log, and the outbox event — Room was
    the only aggregate structurally protected against this class of bug.

    Deliberately NOT applied to every status-like field in the codebase:
    only fields that are actually governed by ``WorkflowRunner``-declared
    (``@workflow_transition``) transitions belong here. ``BookingLine.status``
    is a documented exception (M11 ruling S1) — a plain field, mutated
    directly by design, with no declared transitions of its own; guarding
    it here would fight its own architecture rather than protect it.
    """

    workflow_guarded_field: str = "status"

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_guarded_value = getattr(self, self.workflow_guarded_field, None)

    def save(self, *args, **kwargs):
        field = self.workflow_guarded_field
        current = getattr(self, field)
        changed = self.pk is not None and self._original_guarded_value != current
        if changed and not is_workflow_active():
            raise ValueError(
                f"{type(self).__name__}.{field} changes must go through a "
                f"WorkflowRunner transition. Attempted to change {field} from "
                f"{self._original_guarded_value!r} to {current!r} without "
                f"proper workflow context."
            )
        super().save(*args, **kwargs)
        self._original_guarded_value = current
