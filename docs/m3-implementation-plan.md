# M3 Implementation Plan: Property + Room (Corrected)

## Current State
- M2.5 (MFA) is complete and approved
- All 686 tests passing
- Working tree clean

## M3 Objective
Build the catalog and the **room operational state machine** — the first real consumer of the workflow substrate.

## Architectural Corrections

### 1. RoomStateEvent Partitioning
**Do NOT partition RoomStateEvent in M3.**
- M7 is the first real partitioning milestone per architectural decision
- Create `RoomStateEvent` as a normal append-only table
- Document future partition seam in code comments if needed
- Defer actual PostgreSQL partitioning to M7

### 2. No Signals for Orchestration
**Do NOT create `apps/rooms/signals.py`.**
- Signals violate M1 rule: no signals for cross-context side effects
- Use existing WorkflowRunner/outbox infrastructure directly
- Single path: `RoomStateMachine.apply() → WorkflowRunner → state mutation → RoomStateEvent → Audit → OutboxEvent → commit`

### 3. PostGIS Infrastructure Check
**PostGIS is NOT ready in current repository:**
- DDS §3 requires `geography(Point,4326)` for property location
- Current `pyproject.toml` has no GIS dependencies
- No `django.contrib.gis` in INSTALLED_APPS
- No PostGIS extension setup
- No Docker/Postgres configuration for PostGIS

**M3 Decision:** Defer PostGIS to a future milestone when infrastructure is prepared.
- Use `latitude DECIMAL(9,6)` + `longitude DECIMAL(9,6)` for property location
- Add B-tree index on `(latitude, longitude)` for basic filtering (NOT true proximity-search optimization)
- **Geographic distance/search semantics and PostGIS are explicitly deferred**
- Document PostGIS migration path for future milestone

## Implementation Order

### 1. Property Hierarchy Models + Migration
**Files:**
- `apps/properties/models.py`
- `apps/properties/migrations/0001_initial.py`
- `apps/properties/migrations/0002_rls.py`

**Models:**
- `Property` (tenant-scoped, soft delete via `deactivated_at`)
- `PropertyGroup` (tenant-scoped, soft delete via `deleted_at`)
- `Building` (tenant-scoped, soft delete)
- `Floor` (tenant-scoped, soft delete)
- `Facility` (tenant-scoped, soft delete)
- `MediaAsset` (tenant-scoped, soft delete)

**Key Features:**
- Tenant-scoped with `tenant_id`
- Hierarchical FKs: `Building.property_id`, `Floor.building_id`, `Facility.property_id`
- Unique constraints with tenant scope
- **Non-PostGIS location:** `latitude DECIMAL(9,6)`, `longitude DECIMAL(9,6)`
- Partial unique indexes for soft-delete safety
- RLS migration pattern matching M1/M2

**Django Patterns:**
- Custom managers inheriting `TenantScopedManager`
- `TextChoices` for status fields
- `CheckConstraint` for enum validation
- `GinIndex` for JSONB fields

### 2. RoomType + Room Models + Migration
**Files:**
- `apps/rooms/models.py`
- `apps/rooms/migrations/0001_initial.py`
- `apps/rooms/migrations/0002_rls.py`

**Models:**
- `RoomType` (tenant-scoped, soft delete via `status='retired'`)
- `Room` (tenant-scoped, soft delete via `deleted_at`)
- `RoomStateEvent` (tenant-scoped, immutable, **NOT partitioned**)
- `RoomConnection` (symmetric connecting-room links)

**Key Features:**
- `Room.operational_state` with `TextChoices` and `CheckConstraint`
- `Room.current_booking_line_id` denormalized occupant pointer
- `RoomStateEvent` append-only audit trail (**no partitioning in M3**)
- Partial index `(room_type_id, id) WHERE operational_state='vacant_clean'` for allocation
- Pessimistic locking on state transitions
- `RoomQuery` selector for allocation candidates

### 3. Room State Machine + Transition Matrix
**Files:**
- `apps/rooms/services.py` (RoomStateMachine)
- `apps/rooms/selectors.py` (RoomQuery)

**States:**
- `vacant_clean` (VC)
- `vacant_dirty` (VD)
- `occupied_clean` (OC)
- `occupied_dirty` (OD)
- `out_of_service` (OOS)
- `out_of_order` (OOO)
- `cleaning` (CL) - ephemeral task state
- `inspected` (IN) - ephemeral task state

**Integration:**
- `RoomStateMachine.apply(room, transition, actor, reason)` - **single entry point**
- Uses existing `WorkflowRunner` from Shared Kernel
- Writes `RoomStateEvent` in same transaction
- Emits `room.state_changed` event through existing outbox
- **NO signals** - direct WorkflowRunner/outbox integration

### 4. RoomQuery Selectors
**Files:**
- `apps/rooms/selectors.py`

**Methods:**
- `RoomQuery.vacant_clean_candidates(room_type_id)` - allocation hot path
- `RoomQuery.by_property(property_id)` - admin views
- `RoomQuery.with_attributes(attributes)` - filtering

### 5. RoomService
**Files:**
- `apps/rooms/services.py`

**Methods:**
- `RoomService.create_room()`
- `RoomService.update_room()`
- `RoomService.retire_room_type()`
- `RoomService.get_room_state_history()`

### 6. API Endpoints
**Files:**
- `apps/properties/api/views.py`
- `apps/properties/api/serializers.py`
- `apps/rooms/api/views.py`
- `apps/rooms/api/serializers.py`

**Endpoints:**
- `GET /api/properties/` - list properties
- `POST /api/properties/` - create property
- `GET /api/properties/{id}/` - get property detail
- `GET /api/rooms/` - list rooms
- `POST /api/rooms/` - create room
- `GET /api/rooms/{id}/` - get room detail
- `POST /api/rooms/{id}/state/` - transition room state (via RoomStateMachine)

### 7. Full Unit/Integration Verification
**Files:**
- `tests/unit/properties/test_models.py`
- `tests/unit/rooms/test_models.py`
- `tests/unit/rooms/test_state_machine.py`
- `tests/unit/rooms/test_selectors.py`
- `tests/unit/rooms/test_services.py`
- `tests/api/test_properties.py`
- `tests/api/test_rooms.py`

**Test Coverage:**
- Transition matrix tests (every allowed/forbidden edge)
- Readiness rule test (VD cannot jump to Vacant Clean)
- State history immutability
- Tenant isolation
- Outbox event emission
- API authentication and permissions

## Room State Transition Matrix

### States
1. **Vacant Clean (VC)** - Ready for allocation
2. **Vacant Dirty (VD)** - Needs cleaning
3. **Occupied Clean (OC)** - Guest in clean room
4. **Occupied Dirty (OD)** - Guest in dirty room
5. **Out of Service (OOS)** - Needs maintenance after cleaning
6. **Out of Order (OOO)** - Under maintenance
7. **Cleaning (CL)** - Housekeeping in progress (ephemeral)
8. **Inspected (IN)** - Cleaning completed, awaiting inspection (ephemeral)

### Transition Matrix

| From State | To State | Trigger | Guard | Permission | Audit | Event |
|------------|----------|---------|-------|------------|-------|-------|
| VC | OC | Guest checks in | Room is VC | `room.allocate` | Yes | `room.state_changed` |
| OC | OD | Stay day rolls | Automatic | System | Yes | `room.state_changed` |
| OD | OC | Daily service | Room is OD | `room.service` | Yes | `room.state_changed` |
| OC | VD | Guest checks out | Room is OC | `room.checkout` | Yes | `room.state_changed` |
| OD | VD | Guest checks out | Room is OD | `room.checkout` | Yes | `room.state_changed` |
| VD | CL | Housekeeper starts | Room is VD | `room.clean` | Yes | `room.state_changed` |
| CL | IN | Housekeeper completes | Room is CL | `room.complete_cleaning` | Yes | `room.state_changed` |
| IN | VC | Inspector approves | Room is IN | `room.approve` | Yes | `room.state_changed` |
| IN | CL | Defect found | Room is IN | `room.reject` | Yes | `room.state_changed` |
| CL | OOS | Defect → maintenance | Room is CL | `room.defect` | Yes | `room.state_changed` |
| VC | OOS | Defect reported | Room is VC | `room.defect` | Yes | `room.state_changed` |
| OC | OOO | Emergency maintenance | Room is OC | `room.maintenance` | Yes | `room.state_changed` |
| VC | OOO | Planned maintenance | Room is VC | `room.maintenance` | Yes | `room.state_changed` |
| OOO | VC | Maintenance resolved | Room is OOO | `room.restore` | Yes | `room.state_changed` |
| OOS | CL | Restored after cleaning | Room is OOS | `room.restore` | Yes | `room.state_changed` |
| CL | IN | Cleaning completed | From OOS path | `room.complete_cleaning` | Yes | `room.state_changed` |
| IN | VC | Inspection approved | From OOS path | `room.approve` | Yes | `room.state_changed` |

### Forbidden Transitions
1. **VD → VC** - Must pass through Cleaning → Inspected (readiness rule)
2. **CL → VC** - Must be inspected first
3. **IN → OOO** - Must go through VC first
4. **OOO → OD** - Cannot become occupied while under maintenance
5. **OOS → OD** - Cannot become occupied while out of service
6. **OOS → VC** - Must pass through Cleaning → Inspected (readiness rule applies)

### Readiness Rule
**Why VD cannot jump directly to Vacant Clean:**
- The core guest-experience and safety guarantee
- Ensures every room is physically cleaned and inspected before allocation
- Prevents "dirty room" incidents that damage reputation
- The workflow enforces this path: VD → Cleaning → Inspected → Vacant Clean
- This is the **single most important invariant** in the room state machine

**Why OOS cannot jump directly to Vacant Clean:**
- OOS rooms have defects that required maintenance
- Must be cleaned and inspected after maintenance before becoming allocatable
- The workflow enforces this path: OOS → Cleaning → Inspected → Vacant Clean
- Same readiness guarantee applies to both VD and OOS restoration

### Guard Examples
1. **VD → Cleaning:** Room must be Vacant Dirty
2. **CL → IN:** Room must be in Cleaning state
3. **IN → VC:** Inspector must have `room.approve` permission
4. **VC → OOO:** Room must be Vacant Clean for planned maintenance

### Permission Examples
1. **room.allocate:** Front desk or allocation engine
2. **room.clean:** Housekeeping staff
3. **room.approve:** Housekeeping supervisor
4. **room.maintenance:** Maintenance staff
5. **room.restore:** Maintenance supervisor

## M3 Boundary Clarification

**RoomStateMachine owns room operational state transitions, but M3 does NOT invent workflows:**

- **VC → OC** supports check-in transition, but M3 does not decide a guest has checked in
- **OC → OD** is a valid transition, but M3 does NOT implement:
  - Any scheduler
  - Booking-day-roll process
  - Automatic trigger mechanism
  - Later Booking/Allocation workflows will invoke this transition when needed
- Later Booking/Allocation/Housekeeping workflows will invoke these transitions
- M3 provides the state machine infrastructure, not the business process orchestration

## Exit Gate
- Transition matrix tests pass (every allowed/forbidden edge)
- Readiness rule test passes (VD cannot jump to Vacant Clean)
- State history immutability verified
- Tenant isolation enforced
- Outbox events emitted correctly
- Code review approved
- All unit and integration tests green

## Deferred to Future Milestones
- PostGIS infrastructure and migration
- RoomStateEvent partitioning (M7)
- Booking/Allocation/Housekeeping workflows that invoke room state transitions