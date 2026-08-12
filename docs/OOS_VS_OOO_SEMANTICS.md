# OOS vs OOO Semantics Documentation

## State Definitions

### OUT_OF_SERVICE (OOS)

**Meaning**: Room has a **defect** that makes it uninhabitable

**Examples**:
- Broken plumbing
- Electrical issues
- Structural damage
- Major maintenance required
- Health/safety hazards

**Characteristics**:
- Room is **physically damaged or unsafe**
- Requires **repairs** before it can be used
- Must go through **cleaning/inspection** after repairs
- Cannot be allocated to guests

### OUT_OF_ORDER (OOO)

**Meaning**: Room is **temporarily unavailable** for routine maintenance

**Examples**:
- Routine maintenance
- Preventive inspections
- Cosmetic updates
- Furniture replacement
- Non-critical repairs

**Characteristics**:
- Room is **physically intact and safe**
- Maintenance is **planned/routine**
- Does **not** require cleaning after maintenance
- Can be restored directly to service

## Restoration Paths

### OOS → Cleaning (via `restore`)

**Why**: Defects often leave physical residue or require verification

**Process**:
```
OUT_OF_SERVICE
    ↓ restore (repairs completed)
CLEANING (physical cleanup, residue removal)
    ↓ complete_cleaning
INSPECTED (quality verification)
    ↓ approve
VACANT_CLEAN (ready for allocation)
```

**Rationale**:
- Defect repairs may leave debris, dust, or residue
- Room needs thorough cleaning before guest use
- Inspection ensures repairs were done properly
- Maintains quality standards

### OOO → Vacant Clean (via `restore_direct`)

**Why**: Routine maintenance preserves room condition

**Process**:
```
OUT_OF_ORDER
    ↓ restore_direct (maintenance completed)
VACANT_CLEAN (ready for allocation)
```

**Rationale**:
- Routine maintenance maintains cleanliness
- No physical residue or damage
- Room was clean before maintenance
- Maintenance staff follow clean procedures
- Direct restoration is safe and efficient

## Domain Distinction

### Critical Invariant: Readiness for Allocation

**OUT_OF_SERVICE**: Room is **unready** due to physical issues
- Requires repairs + cleaning + inspection
- Cannot guarantee guest satisfaction

**OUT_OF_ORDER**: Room is **ready** but temporarily unavailable
- Maintenance preserves readiness
- Can be allocated immediately after maintenance

### Business Impact

**OOS**:
- Higher cost (repairs + cleaning + inspection)
- Longer downtime
- Potential revenue loss
- Guest dissatisfaction if allocated prematurely

**OOO**:
- Lower cost (routine maintenance only)
- Shorter downtime
- Preventive (avoids future OOS)
- Guest satisfaction maintained

## Implementation Verification

### Test Cases

```python# OOS restoration requires cleaning/inspection
room = Room(operational_state=Room.OperationalState.OUT_OF_SERVICE)
RoomStateMachine.apply(room, "restore", actor, reason="Repairs done")
assert room.operational_state == Room.OperationalState.CLEANING

# OOO restoration is direct
room = Room(operational_state=Room.OperationalState.OUT_OF_ORDER)
RoomStateMachine.apply(room, "restore_direct", actor, reason="Maintenance done")
assert room.operational_state == Room.OperationalState.VACANT_CLEAN
```

### Forbidden Transitions

```python# ❌ OOS → Vacant Clean (direct bypass)
room = Room(operational_state=Room.OperationalState.OUT_OF_SERVICE)
with pytest.raises(TransitionNotAllowed):
    RoomStateMachine.apply(room, "restore_direct", actor, reason="Invalid")

# ❌ OOO → Cleaning (unnecessary detour)
room = Room(operational_state=Room.OperationalState.OUT_OF_ORDER)
with pytest.raises(TransitionNotAllowed):
    RoomStateMachine.apply(room, "restore", actor, reason="Invalid")
```

## Real-World Examples

### OOS Scenario

**Situation**: Guest reports water leak from bathroom

**Process**:
1. Mark room as OUT_OF_SERVICE
2. Plumber repairs pipe (may leave debris)
3. Housekeeping cleans thoroughly
4. Inspector verifies quality
5. Room becomes VACANT_CLEAN

### OOO Scenario

**Situation**: Scheduled HVAC maintenance

**Process**:
1. Mark room as OUT_OF_ORDER
2. Technician services HVAC (no mess)
3. Room becomes VACANT_CLEAN immediately
4. Ready for next guest

## Conclusion

The OOS/OOO distinction is **intentional and critical** for:
- **Quality control**: Ensures defective rooms are properly cleaned
- **Efficiency**: Allows routine maintenance without unnecessary steps
- **Guest satisfaction**: Maintains high standards
- **Operational clarity**: Clear processes for different scenarios

This is **not** an accidental implementation choice but a deliberate domain design that preserves the readiness invariant while optimizing operations.