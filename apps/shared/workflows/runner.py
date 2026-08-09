"""Workflow substrate — a thin WorkflowRunner over django-fsm (M1.6, DR-07).

Every business process is modeled as a declarative state machine in its own
domain (states/transitions/guards/events/permissions) and executed through
this shared substrate (SDD §9.1.2, §9.2). django-fsm provides the state
persistence and enforcement; the runner adds the contract the roadmap names:

- ``guard``   → django-fsm ``conditions`` (predicates over the entity)
- ``permissions`` → django-fsm ``permission`` (roles allowed to trigger)
- ``events``  → the domain event emitted on transition, written to the
  transactional outbox (DR-08) so side effects are structurally tied to the
  state change — never scattered calls
- ``audit``   → always on: every transition writes an AuditLog row

All of it runs in ONE transaction: state change + outbox row + audit entry
commit or roll back together. A concurrency or guard failure aborts all of it.
"""

from django.db import transaction
from django_fsm import has_transition_perm

from apps.shared.exceptions import TransitionNotAllowed
from apps.shared.services.audit import AuditService
from apps.shared.services.outbox import OutboxService


def workflow_transition(*, field="state", source=None, target, event=None,
                        conditions=None, permission=None):
    """Declare a workflow transition that emits ``event`` on success.

    A thin wrapper over django-fsm's ``transition``: ``conditions`` are the
    guards, ``permission`` the allowed roles, and ``event`` the domain event
    type published through the outbox by the runner. ``audit`` is implicit —
    the runner always records it.
    """
    from django_fsm import transition  # import kept local to avoid startup coupling

    return transition(
        field=field,
        source=source,
        target=target,
        conditions=conditions,
        permission=permission,
        custom={"event": event} if event else {},
    )


class WorkflowRunner:
    """Executes declared transitions with guard/permission/event/audit behavior.

    Usage::

        runner = WorkflowRunner(instance)
        if runner.can_run("confirm"):
            runner.run("confirm", actor=request.user, reason="guest confirmed")

    ``run`` raises ``TransitionNotAllowed`` if the transition is undefined or
    not currently available (a guard failed), and ``ConcurrencyError`` if the
    entity changed underneath us — the whole workflow rolls back in both cases.
    """

    def __init__(self, instance, *, field="state"):
        self.instance = instance
        self.field = field

    @property
    def state(self):
        return getattr(self.instance, self.field)

    def transitions(self) -> dict[str, object]:
        """All declared transitions, keyed by method name."""
        getter = getattr(self.instance, f"get_all_{self.field}_transitions")
        return {t.name: t for t in getter()}

    def available(self) -> list[str]:
        """Transition names whose source matches and guards pass.

        Note: like django-fsm's own ``get_available_*_transitions``, this does
        NOT evaluate permissions — a transition can be structurally available
        yet forbidden to a given principal. Use ``can_run`` for the full check.
        """
        getter = getattr(self.instance, f"get_available_{self.field}_transitions")
        return [t.name for t in getter()]

    def can_run(self, name: str, actor=None) -> bool:
        """True if the transition is available AND ``actor`` is permitted."""
        if name not in self.available():
            return False
        return has_transition_perm(getattr(self.instance, name), actor)

    def run(self, name: str, *, actor=None, reason: str = "", request_id: str = ""):
        all_transitions = self.transitions()
        if name not in all_transitions:
            raise TransitionNotAllowed(
                f"{name!r} is not a declared transition on {type(self.instance).__name__}"
            )
        if not self.can_run(name, actor=actor):
            raise TransitionNotAllowed(
                f"{name!r} is not available from state {self.state!r}"
            )
        transition = all_transitions[name]
        event_type = (transition.custom or {}).get("event")
        entity_type = type(self.instance).__name__.lower()
        entity_id = str(self.instance.pk)

        with transaction.atomic():
            before = self.state
            getattr(self.instance, name)()  # django-fsm enforces guards, sets state
            self.instance.save()  # transitions change state in memory only
            after = self.state

            if event_type:
                OutboxService.record_event(
                    event_type=event_type,
                    tenant_id=self.instance.tenant_id,
                    aggregate_type=entity_type,
                    aggregate_id=entity_id,
                    payload={"from": before, "to": after},
                )
            AuditService.record(
                tenant_id=self.instance.tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=name,
                before={"state": before},
                after={"state": after},
                actor=actor,
                reason=reason,
                request_id=request_id,
            )
        return self.instance
