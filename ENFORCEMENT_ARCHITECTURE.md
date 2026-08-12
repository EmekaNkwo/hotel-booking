# Single-Entry-Point Enforcement Architecture

## Overview

This document describes the corrected architecture for enforcing that all Room state transitions must go through `RoomStateMachine.apply()`, preventing direct calls to django-fsm transition methods.

## Corrected Dependency Direction

The initial implementation violated architectural boundaries by making `apps/shared` depend on `apps/rooms`. This has been corrected:

```
apps/shared/workflows/context.py (Shared Kernel)
    ↓
apps/shared/workflows/runner.py (Shared Kernel)
    ↓
apps/rooms/models.py (Rooms bounded context)
```

## Architecture Components

### 1. Shared Workflow Context (`apps/shared/workflows/context.py`)

A generic, domain-independent context mechanism:

- **Thread-local storage**: Safe for multi-threaded execution
- **Context variables**: Safe for async execution  
- **WorkflowContext**: Context manager that marks workflow execution
- **is_workflow_active()**: Function to check if in workflow context

```python
# Usage in WorkflowRunner
with WorkflowContext():
    # Execute transition
    # State changes allowed here
    pass
```

### 2. WorkflowRunner Integration (`apps/shared/workflows/runner.py`)

The runner wraps transition execution in WorkflowContext:

```python
def run(self, name: str, *, actor=None, reason: str = "", request_id: str = ""):
    # ... validation ...
    with transaction.atomic():
        with WorkflowContext():  # ← Marks workflow execution
            before = self.state
            getattr(self.instance, name)()  # Call transition
            self.instance.save()  # Save with context marker set
            after = self.state
            # ... audit, outbox, etc ...
```

### 3. Room Model Enforcement (`apps/rooms/models.py`)

The Room model enforces single-entry-point invariant:

```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._original_operational_state = self.operational_state

def save(self, *args, **kwargs):
    # Check if state changed
    state_changed = (
        self.pk is not None and
        self._original_operational_state != self.operational_state
    )
    
    # Block if changed outside workflow context
    if state_changed and not is_workflow_active():
        raise ValueError(
            f"Room state changes must go through RoomStateMachine.apply(). "
            f"Attempted to change state from {self._original_operational_state} "
            f"to {self.operational_state} without proper workflow context."
        )
    
    super().save(*args, **kwargs)
    self._original_operational_state = self.operational_state
```

## Enforcement Behavior

### ✅ Allowed: RoomStateMachine.apply()

```python
room = Room.objects.get(pk=101)
updated_room = RoomStateMachine.apply(room, "allocate", actor=user, reason="Guest check-in")
# ✅ Works: audit, outbox, permissions, events all created
```

### ❌ Blocked: Direct transition call

```python
room = Room.objects.get(pk=101)
room.allocate()  # Changes state in memory
room.save()      # ❌ Raises ValueError: "Room state changes must go through RoomStateMachine.apply()"
```

## Verification Tests

### Test Coverage

1. **Direct transition blocking**: `test_direct_transition_call_is_blocked`
2. **Proper path works**: `test_room_state_machine_still_works`
3. **Audit trail**: `test_audit_is_written`
4. **Outbox events**: `test_outbox_event_is_written`
5. **Permissions**: `test_permission_checks_still_apply`
6. **Atomicity**: `test_atomic_operation`
7. **All transitions**: `test_all_transitions_enforced`
8. **Concurrency**: `test_concurrent_state_change_prevented`
9. **Dependency direction**: `test_shared_context_is_independent`
10. **Context mechanism**: `test_workflow_context_works`

### Test Files

- `tests/unit/rooms/test_enforcement_final.py` - Comprehensive enforcement tests
- `tests/unit/rooms/test_dependency_direction.py` - Architecture boundary tests
- `tests/unit/rooms/test_state_machine.py` - Existing state machine tests

## Benefits

1. **Real Enforcement**: Not just naming convention - actually prevents bypass
2. **Architectural Integrity**: Maintains proper dependency direction
3. **Thread-Safe**: Uses thread-local storage for multi-threaded environments
4. **Async-Safe**: Uses context variables for async contexts
5. **Generic**: Can be used by other workflows in the future
6. **Clear Errors**: Provides actionable error messages
7. **No Performance Impact**: Only checks when state actually changes
8. **Backward Compatible**: Existing code continues to work

## Migration Safety

The enforcement mechanism is designed to be safe:

- **No schema changes**: No new migrations needed
- **No breaking changes**: Existing RoomStateMachine.apply() calls work unchanged
- **Clear error messages**: Directs developers to the correct API
- **Test coverage**: Comprehensive tests prevent regressions

## Future Extensibility

The shared workflow context can be used by other bounded contexts:

```python
# Future: apps/reservations/models.py
from apps.shared.workflows.context import is_workflow_active

class Reservation(models.Model):
    def save(self, *args, **kwargs):
        if self.state_changed() and not is_workflow_active():
            raise ValueError("Use ReservationWorkflow.apply()")
        super().save(*args, **kwargs)
```

## Summary

The corrected architecture:

- ✅ Maintains proper dependency direction (Shared → Rooms, not Rooms → Shared)
- ✅ Enforces single-entry-point invariant for all 12 transitions
- ✅ Preserves all existing functionality (audit, outbox, permissions)
- ✅ Provides clear error messages for violations
- ✅ Is thread-safe and async-safe
- ✅ Can be extended to other workflows in the future