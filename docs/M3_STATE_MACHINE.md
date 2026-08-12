# M3 Room State Machine Implementation

## Overview

The Room State Machine implements a closed-set operational state vocabulary with validated transitions using django-fsm and WorkflowRunner integration.

## State Definitions

### Operational States

- **vacant_clean**: Room is empty and ready for guest allocation
- **vacant_dirty**: Room is empty but needs cleaning
- **occupied_clean**: Room is occupied and in good condition
- **occupied_dirty**: Room is occupied and needs service
- **out_of_service**: Room has defects and cannot be allocated
- **out_of_order**: Room is temporarily unavailable for maintenance
- **cleaning**: Room is actively being cleaned (ephemeral)
- **inspected**: Room has been cleaned and is awaiting inspection (ephemeral)

### Ephemeral States

`cleaning` and `inspected` are transient states that must be resolved quickly:
- `cleaning` → `inspected` (via `complete_cleaning`)
- `inspected` → `vacant_clean` (via `approve`) or `cleaning` (via `reject`)

## Transition Matrix

### From Vacant Clean

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `allocate` | occupied_clean | Guest check-in |
| `defect` | out_of_service | Defect found |
| `maintenance` | out_of_order | Maintenance needed |

### From Occupied Clean

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `service` | occupied_dirty | Room service requested |
| `checkout` | vacant_dirty | Guest checkout |
| `maintenance` | out_of_order | Maintenance needed |

### From Occupied Dirty

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `service_complete` | occupied_clean | Service completed |
| `checkout` | vacant_dirty | Guest checkout |

### From Vacant Dirty

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `clean` | cleaning | Start cleaning process |

### From Cleaning

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `complete_cleaning` | inspected | Cleaning completed |
| `defect` | out_of_service | Defect found during cleaning |

### From Inspected

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `approve` | vacant_clean | Inspection passed |
| `reject` | cleaning | Needs more cleaning |

### From Out of Service

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `restore` | cleaning | Repairs completed (must go through cleaning) |

### From Out of Order

| Transition | Target State | Description |
|-----------|--------------|-------------|
| `restore_direct` | vacant_clean | Maintenance completed (no cleaning needed) |

## Forbidden Transitions

### Critical Invariant

**Vacant Dirty → Vacant Clean is explicitly forbidden**

A room cannot bypass the cleaning/inspection process:
```
❌ vacant_dirty → vacant_clean (FORBIDDEN)
✅ vacant_dirty → cleaning → inspected → vacant_clean (REQUIRED)
```

### Other Forbidden Transitions

- `vacant_dirty` cannot use `allocate`, `defect`, `maintenance`
- `cleaning` cannot use `allocate`, `checkout`, `service`, etc.
- `inspected` cannot use `checkout`, `service`, etc.
- `out_of_service` cannot go directly to `vacant_clean`

## Implementation Architecture

### Components

1. **Room Model**: Defines states and django-fsm transitions
2. **WorkflowRunner**: Handles transition execution, audit, and outbox
3. **RoomStateMachine**: Single entry point (`apply()` method)
4. **RoomStateEvent**: Append-only audit trail
5. **AuditService**: Records state changes atomically
6. **OutboxService**: Emits `room.state_changed` events

### Data Flow

```
RoomStateMachine.apply(room, transition, actor, reason)
    ↓
WorkflowRunner.run()
    ↓
django-fsm transition (validates guards)
    ↓
Room.save() (atomic)
    ↓
AuditService.record() (same transaction)
    ↓
OutboxService.record_event() (same transaction)
```

### Transactional Guarantees

- **Atomicity**: State change, audit entry, and outbox event commit together
- **Isolation**: Tenant-scoped operations
- **Durability**: All changes persisted to database
- **Consistency**: Invalid transitions rejected before any writes

## API

### RoomStateMachine.apply()

```python
RoomStateMachine.apply(
    room: Room,
    transition_name: str,  # e.g., "allocate", "checkout"
    actor: Any,            # User or system actor
    reason: str = ""       # Human-readable reason
) -> Room
```

**Returns**: Updated Room instance
**Raises**: `TransitionNotAllowed` if transition is undefined or forbidden

### Example Usage

```python
# Allocate a room to a guest
room = Room.objects.get(pk=101)
updated_room = RoomStateMachine.apply(
    room, 
    "allocate", 
    actor=request.user, 
    reason="Guest check-in"
)

# Guest checks out
updated_room = RoomStateMachine.apply(
    updated_room,
    "checkout",
    actor=request.user,
    reason="Guest checkout"
)

# Clean the room
updated_room = RoomStateMachine.apply(
    updated_room,
    "clean",
    actor=housekeeping_user,
    reason="Housekeeping assigned"
)
```

## Testing Strategy

### Test Coverage

1. **Allowed Transitions**: Test every valid transition
2. **Forbidden Transitions**: Test explicitly forbidden transitions
3. **Invalid Transitions**: Test undefined/nonexistent transitions
4. **State Machine Integration**: Test full workflows
5. **Atomicity**: Verify no partial writes on failure
6. **Tenant Isolation**: Verify tenant-scoped operations
7. **Audit Trail**: Verify RoomStateEvent creation
8. **Outbox Events**: Verify event emission

### Test Cases

- ✅ `test_allocate_vacant_clean_to_occupied_clean`
- ✅ `test_checkout_occupied_clean_to_vacant_dirty`
- ✅ `test_clean_vacant_dirty_to_cleaning`
- ✅ `test_complete_cleaning_to_inspected`
- ✅ `test_approve_inspected_to_vacant_clean`
- ✅ `test_reject_inspected_to_cleaning`
- ✅ `test_service_occupied_clean_to_occupied_dirty`
- ✅ `test_service_complete_occupied_dirty_to_occupied_clean`
- ✅ `test_defect_vacant_clean_to_out_of_service`
- ✅ `test_maintenance_occupied_clean_to_out_of_order`
- ✅ `test_restore_out_of_service_to_cleaning`
- ✅ `test_restore_direct_out_of_order_to_vacant_clean`

### Forbidden Transition Tests

- ✅ `test_vacant_dirty_cannot_go_directly_to_vacant_clean`
- ✅ `test_invalid_transition_from_vacant_clean`
- ✅ `test_undefined_transition`

### Integration Tests

- ✅ `test_full_cleaning_cycle` (VD → Cleaning → Inspected → VC)
- ✅ `test_state_event_immutability`
- ✅ `test_tenant_isolation`

## Verification Checklist

### Code Quality

- [ ] Ruff linting passes
- [ ] `manage.py check` passes
- [ ] `makemigrations --check --dry-run` shows no changes needed
- [ ] Type hints are correct
- [ ] Import sorting is clean

### Testing

- [ ] All unit tests pass
- [ ] Integration tests pass
- [ ] Postgres integration tests pass
- [ ] Test coverage ≥ 95%

### Documentation

- [ ] State definitions are clear
- [ ] Transition matrix is complete
- [ ] Forbidden transitions are documented
- [ ] API usage examples provided
- [ ] Architectural decisions justified

## Design Decisions

### Why django-fsm?

- **Proven**: Battle-tested state machine library
- **Integrated**: Works seamlessly with Django models
- **Simple**: Declarative transition definitions
- **Compatible**: Works with existing WorkflowRunner

### Why WorkflowRunner?

- **Consistent**: Same pattern used throughout the application
- **Complete**: Handles audit, outbox, and transactions
- **Maintainable**: Single entry point for state changes
- **Testable**: Easy to mock and test

### Why No Signals?

- **Explicit**: State changes are intentional, not reactive
- **Traceable**: All transitions go through RoomStateMachine.apply()
- **Reliable**: No hidden side effects
- **Testable**: Easy to verify behavior

### Why No Direct State Assignment?

- **Safety**: All state changes must go through the state machine
- **Audit**: Every change is recorded
- **Validation**: Transitions are validated before execution
- **Events**: Domain events are emitted consistently

## Future Considerations

### Deferred to M7

- **Partitioning**: RoomStateEvent partitioning by tenant/date
- **Performance**: Optimization for high-volume state changes
- **Monitoring**: Alerts for stuck ephemeral states
- **Analytics**: State transition metrics and reporting

### Not Implemented (Out of Scope)

- **Booking/Allocation**: No booking workflow integration
- **Housekeeping**: No automatic scheduling
- **Day Roll**: No automatic state transitions
- **Maintenance**: No preventive maintenance scheduling

## Migration Notes

### Database Changes

- **RoomStateEvent table**: Created in 0001_initial.py
- **RLS policies**: Created in 0002_rls.py
- **No data migration**: Starting from clean state

### Backward Compatibility

- **New feature**: No existing code to break
- **Clean slate**: Starting with empty database
- **API stable**: RoomStateMachine.apply() is the only public API

## Performance Characteristics

### Read Operations

- **State queries**: O(1) - indexed operational_state field
- **Transition history**: O(log n) - indexed RoomStateEvent
- **Allocation candidates**: O(log n) - partial index on (room_type, operational_state)

### Write Operations

- **State transition**: O(1) - single row update
- **Audit entry**: O(1) - append-only insert
- **Outbox event**: O(1) - append-only insert
- **Transaction**: O(1) - all operations in single transaction

### Concurrency

- **Optimistic locking**: Version field on Room model
- **Isolation**: Serializable transactions
- **Conflict resolution**: Retry on version conflict

## Error Handling

### TransitionNotAllowed

- **Cause**: Invalid or forbidden transition
- **Effect**: No state change, no audit entry, no outbox event
- **Recovery**: Client must choose valid transition

### Database Errors

- **Cause**: Constraint violation, connection failure
- **Effect**: Transaction rolls back completely
- **Recovery**: Retry with exponential backoff

### Validation Errors

- **Cause**: Invalid actor, missing reason
- **Effect**: Rejected before transaction starts
- **Recovery**: Fix input and retry

## Monitoring and Observability

### Metrics

- **State transitions**: Count by type and state
- **Transition time**: Duration of state changes
- **Error rate**: Failed transition attempts
- **Ephemeral states**: Time spent in cleaning/inspected

### Logging

- **Audit trail**: Complete history in RoomStateEvent
- **Domain events**: room.state_changed events
- **Application logs**: Transition attempts and outcomes

### Alerts

- **Stuck states**: Rooms in cleaning/inspected too long
- **Failed transitions**: Repeated transition failures
- **Invalid transitions**: Attempts to bypass state machine

## Conclusion

The Room State Machine provides a robust, auditable, and maintainable foundation for room operational state management. It enforces business rules, ensures data integrity, and integrates seamlessly with the existing application architecture.