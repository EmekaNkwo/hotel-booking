# Hospitality Management Platform — Implementation Roadmap

| Field | Value |
|---|---|
| **Status** | v1.0 — the build plan |
| **Version** | 1.0 |
| **Date** | 2026-08-05 |
| **Author** | Technical Lead |
| **Source of truth** | SDD v0.3 · DMS v1.0 · DDS v1.0 (approved — no redesign unless a critical flaw is found) |
| **Assumed stack** | Python 3.13+ · **Django 5.2 LTS** · DRF · PostgreSQL 16 · Redis · Celery · Docker · Pytest · factory_boy · drf-spectacular · django-filter |

**Scope:** the roadmap only. No code. Each milestone names the bounded context(s), the Django concepts we will learn, the key decisions, and the review gate that must pass before the next milestone begins.

---

## 1. How this roadmap works

Four rules drive every ordering decision:

1. **Backbone before business.** The Shared Kernel (Money, DateRange, events, outbox, idempotency, audit, workflow substrate) is needed by every context. Building it first means the first real feature already has the discipline wired in — retrofitting the outbox or RLS later is expensive and risky (DMS Risks #8, #11).
2. **Ask-before-sell.** Policy must exist before Pricing, Reservation, Booking, or Payments *ask* it (DR-10). The engines are built bottom-up so that Booking — the orchestration payoff — is the capstone, not the first guess.
3. **One context, one coherent lesson.** Each milestone teaches a small, named set of Django concepts and exercises them in real business code. We never introduce a Django feature for its own sake.
4. **v1 first, v2/v3 deferred.** Maintenance, Guest Services, Loyalty, coupons/dynamic pricing, group bookings, search personalization, OTA/channel manager are out of v1 (SDD §1.3). They are real milestones in this plan but come *after* the v1 exit criteria are met.

**Review gate:** every milestone ends with code review + green tests + a short retro. We do not start the next milestone until the current one is reviewed. The SDD/DMS/DDS are consulted before every decision; if the code wants to deviate, we discuss it as a *design change*, not a silent shortcut.

---

## 2. Critical early decisions (locked in M0–M1, affect everything after)

| # | Decision | Why it must be early | Where it lands |
|---|---|---|---|
| E1 | **Custom User model** (`AUTH_USER_MODEL` → `accounts.UserAccount`) | Django requires this **before the first migration**; changing later is a documented pain point. `user_account` is platform-global (no `tenant_id`), so it is also where the "platform vs tenant" boundary becomes concrete. | M0 decision, M2 build |
| E2 | **Tenant context = middleware + `set_config('app.tenant_id')` + RLS** | RLS is on *every* table (DDS A.2, DMS Risk #11). The middleware/context plumbing is the spine of the whole app; building one CRUD context before it means building it twice. | M2 |
| E3 | **Enums = `TextChoices` + explicit `CheckConstraint`** (never native PG ENUM) | DDS A.1. The pattern is repeated in ~40 tables; it is taught once (M1) and reused everywhere. | M1 + every milestone |
| E4 | **Money = `shared.Money` value object (int minor units) over `BIGINT` + `CHAR(3)` columns** | DMS Risk #13, DDS A.1. Never a float. The value object is taught in M1; every monetary table uses it. | M1 + M6/M9/M10 |
| E5 | **No Django signals for cross-context effects — events + outbox only** | SDD DR-08. Signals are order-dependent and invisible; the outbox makes side effects atomic and replayable. We will teach signals only to explain *why we don't use them* for this. | M1 + every milestone |
| E6 | **Repository pattern only where it provides real value** | DMS lists repositories per context; in Django we implement them **only** for aggregates with real invariants — availability's atomic conditional update, booking confirm, payment idempotency. Everything else uses managers/querysets + selectors. This is the reconciliation between DMS §"Repositories" and the ORM. | M1 principle; M7/M9/M10 concrete |
| E7 | **Partitioning via `RunSQL` + a partition-management task, not ORM-native** | Django has no first-class declarative-partitioning support. The DDS mandates partitions up front (R16). We own partition DDL in migrations and lifecycle in a Celery task, taught once at the first partitioned table. | M0 strategy; M7 first real partition |
| E8 | **No GenericForeignKey for events/audit entity refs** | GFK has no FK integrity and invites N+1. `audit_log`/`domain_event` reference entities via typed `entity_type` + `entity_id` columns (no FK), with RLS tenant scoping as the safety net. We will explain GFK and why we reject it. | M1 |
| E9 | **Versioning discipline:** events carry a schema version from day one (DMS Risk #8); policies are append-only version rows; snapshots (price/guest/policy) are JSONB, never live refs | Retrofitting event versioning is the single most expensive refactor in event-driven systems. | M1 + M6/M9/M21 |
| E10 | **Soft delete policy from DDS A.5** | Operational tables never hard-delete; config tables use `status`/`deleted_at` + partial unique indexes. Decided now so every model follows the same rule. | M1 + every milestone |

---

## 3. Milestone map

| # | Milestone | Bounded context(s) / apps | New Django concepts | New infrastructure |
|---|---|---|---|---|
| **M0** | Foundation & Bootstrap | `shared` (skeleton), project shell | settings modules, project layout, apps, env/12-factor, docker-compose, pytest-django, factory_boy | Postgres, Redis, Celery, Docker |
| **M1** | Shared Kernel backbone | `shared`: value objects + events/outbox/idempotency/audit/workflow | dataclasses as value objects, `JSONField`, `CheckConstraint`, partial indexes, `RunSQL`, migrations discipline, `transaction.atomic`, `on_commit`, F()/conditional updates, abstract base models | outbox relay (skeleton), audit writer |
| **M2** | Tenancy + Identity & Access | `tenants`, `accounts` | Custom User model, Managers/QuerySets (tenant scoping), middleware + `set_config`, RLS via `RunSQL`, RBAC-as-data vs Django auth, `AbstractBaseUser`/`PermissionsMixin`, invitation flow | principal cache (Redis) |
| **M3** | Property + Room | `properties`, `rooms` | model relationships (FK across apps), `Meta` constraints (`UniqueConstraint`, `CheckConstraint`), `TextChoices`, partial indexes, **first workflow on the substrate** (room state machine) | — |
| **M4** | Policy Engine | `policies` | service layer (application services), the "ask don't embed" contract, append-only versioning, `PolicyService.can_cancel/refund_rule/deposit_required` | policy-version cache |
| **M5** | Guest Profile | `guests` | `CITEXT` extension + custom fields, JSONB storage, identity resolution selector, partial unique indexes, GDPR erasure flow | — |
| **M6** | Pricing | `pricing` | `ExcludeConstraint` + range operators, `Money` in service math, `PriceBreakdown` snapshot, `PricingService.price()` | — |
| **M7** | Availability & Inventory (merged) | `availability`, `inventory` | `select_for_update`, `GeneratedField`, **partitioned table #1**, atomic conditional updates, partial-index hot path, the "never oversell" repository capability | partition management task |
| **M8** | Reservation | `reservations` | Celery tasks + beat, Redis TTL holds, `on_commit` with events, idempotent expiry sweep | Celery beat schedule |
| **M9** | Booking | `bookings` | orchestration services, per-room-line state machine, derived aggregate status, the T1/T2 atomic confirm transaction | — |
| **M10** | Payments & Ledger | `payments` | idempotency-key pattern, PSP adapter interface, double-entry ledger (app-level balance), async workers for PSP calls | PSP sandbox |
| **M11** | Allocation | `allocation` | deterministic scoring service, selector composition, check-in orchestration (T6) | — |
| **M12** | Housekeeping | `housekeeping` | event *consumers*, night-audit job, plan generation, defect loop to maintenance | night-audit beat task |
| **M13** | Notifications | `notifications` | outbox relay consumer, retry/backoff/DLQ, template resolution, channel preferences | DLQ monitoring |
| **M14** | Reviews + Timeline | `reviews`, `timeline` | read models, idempotent projections, projection checkpointing, review solicitation timing | — |
| **M15** | Reporting + Search | `reporting`, `search` | nightly committed snapshots, OLAP copy, external index (OpenSearch) projection, search→availability→pricing pipeline | OpenSearch |
| **M16** | v1 Hardening & exit criteria | cross-cutting | degraded mode (`payment_pending`), second-approval + break-glass audit, RLS cross-tenant tests, load test of the oversell race | load-test harness |
| **M17** | v2 scope | `maintenance`, `guestservices`, loyalty, coupons, dynamic pricing, group blocks, guest timeline, digital keys, AI concierge adapter | consumer scaling, rule-based dynamic pricing, group pick-up, provider adapters | (v2) |
| **M18** | v3 scope | OTA/channel manager, revenue management, enterprise SSO, virtual credit cards | external sync, webhook security, SSO (OIDC/SAML), VCC flows | (v3) |

---

## 4. Detailed milestones

### M0 — Foundation & Bootstrap

**Goal:** a runnable skeleton — Dockerized Postgres/Redis/Celery, a Django project with the modular-monolith app layout, a green test suite, and the first Shared Kernel value objects. Nothing business-like yet.

**What we build**
- Repo layout: `config/` (settings package), `apps/` (one Django app per bounded context, in the DDS order), `docs/`, `tests/`, `compose.yaml`, `pyproject.toml`, `.env.example`, CI skeleton.
- Settings split `dev / test / prod` with 12-factor env; `pytest-django` + `factory_boy` + `django-debug-toolbar` wired; DRF + drf-spectacular + django-filter installed and enabled (empty but configured).
- First `shared` value objects as pure-Python dataclasses: `Money`, `Currency`, `DateRange`, `StayPeriod`, `GuestCount`, `Email`, `PhoneNumber`, `Address`, `GeoLocation`, `TimeZoneId`, typed IDs. These are **not Django models** — they are the cross-context vocabulary (DR-09).

**Django concepts learned**
- Settings modularization and the 12-factor discipline — why a `config/settings/*.py` package beats one monolithic `settings.py`, and why secrets come from env, never the repo.
- The app registry and the modular-monolith layout — why one Django app per bounded context keeps imports honest (DMS dependency map).
- `pytest-django` + `factory_boy` foundations — fixtures, `@pytest.mark.django_db`, factories as the test-data idiom for every later milestone.
- Why we set `AUTH_USER_MODEL` now (E1), even though we build accounts in M2.

**Review gate:** `docker compose up` → migrations run → `pytest` green. Agree the settings contract and app list before any model exists.

---

### M1 — Shared Kernel backbone (events, outbox, idempotency, audit, workflow substrate)

**Goal:** the reliability spine every context leans on — the `domain_event` / `outbox_event` / `idempotency_record` / `audit_log` / `projection_state` tables (DDS §22), the `WorkflowRunner`, and the Money/DateRange vocabulary finalized.

**What we build**
- **Events & outbox:** a `DomainEvent` envelope (id, type, **version**, occurred_at, tenant_id, payload) and the transactional outbox pattern: state change + outbox row in one `atomic()`, a relay that promotes `outbox_event → domain_event`, dead-letter with `attempts`/`last_error`.
- **Idempotency:** `idempotency_record` + the "store key + result in the same transaction" semantics that money/booking mutations will call (FR-PAY-05).
- **Audit:** `audit_log` with typed `entity_type`/`entity_id` (no GFK — E8), before/after JSONB, actor, reason, request_id, written in the same transaction.
- **Workflow substrate:** a thin `WorkflowRunner` wrapping `django-fsm` that adds guards, permissions, and event emission to declared state machines (DR-07, SDD §9.2). First consumer comes in M3.
- **Standard patterns:** the `TextChoices` + `CheckConstraint` recipe, the partial-index recipe, the abstract base mixin (created/updated stamps, `tenant_id`, `version` for optimistic locks).

**Django concepts learned**
- `transaction.atomic` + `on_commit` — the difference between "committed to the DB" and "safe to dispatch side effects"; why the outbox lives *inside* the transaction.
- `JSONField`, `CheckConstraint`, partial `Index(condition=…)` — the DDS's CHECK-vs-ENUM and soft-delete rules become concrete.
- `RunSQL` and migration design — the beginning of our DDL policy (E7); where the ORM can and can't express the DDS (partitioning, RLS, range constraints).
- Conditional `UPDATE` / `F()` expressions — the primitive the availability invariant builds on in M7.
- Why **signals are rejected** for cross-context effects (E5) and why **GFK is rejected** for event/audit refs (E8).

**Review gate:** a unit-tested `WorkflowRunner`, an outbox round-trip test (state change → outbox → relay → domain_event → idempotent consumer), audit immutability test.

---

### M2 — Tenancy + Identity & Access (`tenants`, `accounts`)

**Goal:** the platform spine — a tenant lifecycle, a platform-global user, RBAC-as-data scoped by tenant and property, invitations, and **tenant context + RLS enforced end-to-end**.

**What we build**
- `tenant`, `tenant_settings`, `feature_flag` (DDS §2); `user_account` (custom user), `mfa_device`, `role`, `role_permission`, `membership`, `membership_role`, `membership_property_scope`, `invitation` (DDS §1).
- A custom `UserAccount` (`AbstractBaseUser` + `PermissionsMixin`) with platform-global email uniqueness (DMS invariant #1).
- A **TenantContextMiddleware** that resolves the principal once per request and stamps `set_config('app.tenant_id', …)`.
- A **tenant-scoped base Manager/QuerySet** that every future model inherits — auto-filtering `tenant_id` (defense in depth layer 2, DR-01).
- RLS enabled on the first tenant-scoped tables via `RunSQL`, with a repeatable migration pattern all later contexts copy.
- `TenantService.provision()` (idempotent onboarding, FR-TEN-01), `AuthService`, `InvitationService` → `MembershipService` redemption flow, `role_permission` seeded defaults.
- First **DRF API surface**: auth, me, tenants, members, roles — teaching viewsets, serializers, drf-spectacular wiring, django-filter, and our permission classes.

**Django concepts learned**
- Custom User models — `AbstractBaseUser` vs `AbstractUser`, why we start from the base, `AUTH_USER_MODEL` ordering.
- Managers & QuerySets — custom `QuerySet` methods (`.for_tenant()`, `.active()`) and why tenant scoping lives *here*, not in views.
- Middleware — request lifecycle, why tenant context is set once at the edge (SDD §8) and read by the service layer.
- RLS — the `RunSQL` migration recipe, `FORCE ROW LEVEL SECURITY`, and why RLS is the backstop, not the primary (SDD §13.2 honest trade-off).
- Our RBAC vs Django's `auth` groups/permissions — we keep Django's for platform admin, ours (roles-as-data) for domain authorization; custom permission classes in DRF.
- Invitation redemption as a stateful flow — first non-trivial use of `atomic`.

**Review gate:** cross-tenant isolation test (tenant A cannot read tenant B's rows, via API *and* raw SQL under RLS), RBAC matrix tests, provisioning idempotency test.

---

### M3 — Property + Room (`properties`, `rooms`)

**Goal:** the catalog and the **room operational state machine** — the first real consumer of the workflow substrate.

**What we build**
- `property`, `property_group`, `building`, `floor`, `facility`, `media_asset` (DDS §3) with the hierarchy FK chain and soft-delete + partial unique indexes.
- `room_type`, `room`, `room_state_event`, `room_connection` (DDS §4), including the Vacant/Occupied × Clean/Dirty + OOO/OOS machine (SDD §9.3) declared on the substrate: guards (e.g., `VD → Vacant Clean` must pass `Cleaning → Inspected`), permissions, and `room.state_changed` events.
- `RoomQuery` selector — "which rooms of type T are Vacant Clean and not OOO/OOS" — the allocation candidate query, built as one optimized partial-index query (DDS D.1).
- `RoomService` CRUD + `RoomStateMachine.apply()` as the single arbiter of room state (DMS ownership boundary).

**Django concepts learned**
- Model relationships across apps (`ForeignKey`, `SET_NULL`, `RESTRICT`) and how DDS FK actions map to Django `on_delete`.
- `Meta` options: `ordering`, `constraints` (`UniqueConstraint`, `CheckConstraint`, partial unique), `indexes` (partial, GIN via `GinIndex`).
- `TextChoices` end-to-end with a DB `CheckConstraint` so the DB and the ORM enforce the same vocabulary (E3).
- The workflow substrate in anger: states/transitions/guards/permissions/events; why the room machine is *the* test case for the substrate.
- Soft delete in practice — `status` vs `deleted_at` per DDS A.5; why operational history (`room_state_event`) is immutable, not soft-deleted.

**Review gate:** room-state machine transition-matrix tests (every allowed/forbidden edge), readiness-rule test (`VD` cannot jump to `Vacant Clean`), `room.state_changed` emitted and outboxed.

---

### M4 — Policy Engine (`policies`)

**Goal:** versioned, tenant-configurable business rules as data (DR-10) — the "ask, don't embed" contract every downstream context will use.

**What we build**
- `policy` (append-only version rows: `(tenant_id, policy_type, version)`) and `policy_evaluation_log` (DDS §21).
- `PolicyService` with question-style methods: `can_cancel(...)→(allowed, penalty)`, `refund_rule(...)`, `deposit_required(...)`, `cleaning_standard(...)`, `pricing_policy(...)`, `check_in/out(...)`.
- Version pinning: the service returns a version id; booking/quote code will *store* that version id, never re-evaluate against "current" (FR-PLC-03, DMS Risk #14).
- `PolicyEvaluationLog` written for every answered decision (SDD §5 auditability) — async, so the ask path stays fast.

**Django concepts learned**
- The **service layer** pattern in depth: application services that orchestrate, domain decisions owned by the entity/workflow, and why views/serializers must never call this logic directly (DMS layer rules).
- Append-only versioning as a model pattern (new version row on change — no `UPDATE` on published rows).
- Caching the active-version lookup in Redis without breaking the audit trail.
- `JSONField` for declarative `rules` payloads — data, not code.

**Review gate:** policy-change-never-rewrites-bookings test, evaluation-log completeness, cache-invalidation test.

---

### M5 — Guest Profile (`guests`)

**Goal:** the guest lifecycle hub (SDD §11.9) — identity resolution, preferences, consent, GDPR erasure. Built before Booking so Booking can resolve a profile at creation.

**What we build**
- `guest_profile`, `guest_preference`, `guest_consent` (append-only per purpose), `id_document` (hashes only) (DDS §16). Loyalty deferred to v2.
- `GuestService.resolve()` — find-or-create by email/phone within tenant (the booking-time hot path); `ProfileMergeService` (human-reviewed only); `consent.updated` and `guest.identified` events; the erasure flow (anonymize + `erased_at` + consent kept as proof, DDS D.6).
- Partial unique indexes on `(tenant_id, primary_email) WHERE erased_at IS NULL AND merged_into_id IS NULL`.

**Django concepts learned**
- `CITEXT` via the `CITextExtension` migration + custom field — case-insensitive email identity at the DB layer.
- The **selector** pattern (read model queries) as the mirror of services — `GuestQuery` for resolution and for Notifications' consent reads.
- Partial unique indexes to protect natural keys across soft-delete/erasure (DDS A.2).
- Consent as append-only rows, current state = latest row — the "don't mutate legal history" discipline.

**Review gate:** resolution race test (two simultaneous find-or-create → one profile), merge-only-by-human test, erasure leaves FKs intact + scrubs PII.

---

### M6 — Pricing (`pricing`)

**Goal:** rate plans, overrides, modifiers, and the persisted `PriceBreakdown` — the only place price is computed (DR-06).

**What we build**
- `rate_plan`, `rate_override`, `rate_modifier` (DDS §8), with the non-overlapping window guarantee on overrides.
- `PricingService.price(room_type, StayPeriod, GuestCount, context) → PriceBreakdown` — base + calendar + segment + policy floors/ceilings — persisted as a snapshot (DR-06).
- `PriceSimulationService` (v2-ready what-if).
- `rate.changed` event → Search facets (M15).

**Django concepts learned**
- `ExcludeConstraint` + `RangeOperators` — DB-enforced non-overlapping date ranges (DDS A.9).
- `Money` used in real service math — currency-checked addition, no floats, snapshot semantics (E4).
- Service composition with the Policy Engine (`PricingService` asks policy for floors/ceilings).
- Optimistic locking (`version` column) on rate edits (DDS A.6) — low-contention config writes.

**Review gate:** price-breakdown determinism tests, snapshot-immutability test, override-overlap rejection at DB level.

---

### M7 — Availability & Inventory (`availability` + `inventory` merged)

**Goal:** the anti-oversell core — `availability_slot` with atomic conditional updates, the first **partitioned** table, and the merged Inventory capacity operations (DDS §6+7, DMS Risk #1 resolved).

**What we build**
- `availability_slot` (partitioned by month, `GeneratedField` for `remaining`, the `remaining > 0` partial index, the never-negative CHECK), `inventory_block` + `inventory_block_night`, `channel_allocation` (direct-only in v1) (DDS §6+7).
- The **repository capability** — the one place repositories are truly warranted (E6): `AvailabilitySlotRepository.consume_window(...)` = `SELECT … FOR UPDATE` over the window, then conditional `UPDATE … WHERE remaining >= demand`; `release_window(...)` idempotent.
- `AvailabilityService` (reads, cached) and `InventoryService` (holds/sells/releases/blocks) over the same tables — single owner of sellability truth.
- `room.state_changed` consumer: OOO/OOS decrements `out_of_service`; `room.type_retired` closes slots.
- Partition management Celery task (create next month, drop beyond horizon) — the E7 strategy first exercised.

**Django concepts learned**
- `select_for_update()` and why DB row locks — not app retries — are the anti-oversell guarantee (SDD R1).
- `GeneratedField` (Django 5.0+) — computed, stored, indexable, can't drift.
- Declarative partitioning with Django: `RunSQL` partition DDL, `PartitionConfig`-style maintenance, composite PKs with the partition key (DDS D5), and what breaks if you forget the partition key in the PK.
- Conditional `UPDATE ... WHERE` as the atomic invariant check (DDS A.6).

**Review gate:** the oversell race test (two concurrent consumes of the last unit — exactly one wins, the other fails cleanly), idempotent release, partition-rollover test.

---

### M8 — Reservation (`reservations`)

**Goal:** quote → hold → convert → expire, with Redis TTL holds and the Celery expiry sweep (SDD §10.1, FR-RES-02).

**What we build**
- `reservation`, `reservation_line` (DDS §9); the reservation state machine on the substrate.
- `ReservationService.reserve()` (hold capacity + Redis TTL key `hold:{tenant}:{id}` + DB-authoritative `hold_expiry_at`), `convert()`, `expire()` (Celery beat sweep), `cancel()`.
- `reservation.created/expired/converted` events → Inventory (hold/release), Notifications.
- Quote stores `price_snapshot` + `policy_version` (DMS invariant #5).

**Django concepts learned**
- Celery tasks + beat scheduling; why the sweep is *authoritative* over the Redis TTL (R5) and the DB row is the source of truth for expiry.
- Redis as cache-of-a-DB-fact vs source of truth — the discipline that keeps holds consistent.
- `on_commit` + outbox for emitting events exactly once from the transaction.
- Idempotent expiry (TTL and sweep must not double-release — DMS invariant #4).

**Review gate:** hold-expiry releases exactly once, conversion is all-or-nothing, TTL-vs-sweep race test.

---

### M9 — Booking (`bookings`)

**Goal:** the capstone of the sales layer — the confirmed agreement, the **per-room-line state machine**, and the T1/T2 atomic confirm transaction that ties Reservation → Policy → Pricing → Inventory → Payment → events together (SDD §10.2, DDS A.7).

**What we build**
- `booking`, `booking_line`, `cancellation_record`, `modification_record` (DDS §10).
- `BookingService.confirm()` — the single atomic transaction: create booking → consume capacity → create payment intent → mark reservation converted → emit `booking.confirmed` (T1/T2).
- Per-line workflow (`BookingLine` machine); `booking.aggregate_status` as a **derived, stored projection** with the nightly drift check (DMS Risk #12).
- `CancellationService` (policy penalty at the *agreed* version + idempotent refund trigger + inventory release for future nights — T5), `CheckInOutService` (T6/T7 orchestration), `NoShowService` hook (v2, process-manager seam).
- Snapshot columns: `price_snapshot`, `policy_version`, `guest_snapshot` — immutable after confirm (DMS invariants #4/#6/#8).

**Django concepts learned**
- Orchestration services that compose several contexts' services — the heart of the modular monolith.
- Multi-aggregate `atomic()` transaction boundaries and lock ordering (DDS D9) — the hardest correctness lesson in the project.
- Derived state that must not drift — why it's stored, when it's written, how it's reconciled.
- `guest_snapshot` — why we snapshot guest identity rather than FK live (profile merges must never rewrite history).

**Review gate:** full booking-lifecycle integration test (quote → hold → pay → confirm → check-in → check-out → complete), oversell-atomicity at the confirm boundary, cancellation-under-mid-stay-policy-change test, drift-check test.

---

### M10 — Payments & Ledger (`payments`)

**Goal:** idempotent money, PSP abstraction (SAQ-A hosted surface), and the double-entry ledger (DR-08, FR-PAY-01/04/05).

**What we build**
- `payment_intent`, `payment_attempt`, `refund`, `dispute` (DDS §11); `ledger_account`, `ledger_post`, `ledger_entry`.
- `PaymentService.authorize/capture/void/refund` — **idempotency-keyed**, replay-safe (FR-PAY-05); `PaymentIntent` state machine on the substrate.
- PSP as an interface in `integrations` (adapter + sandbox); card data never stored (SAQ-A).
- `LedgerService.post()` — balanced post per business event; `ledger_post.source_event_id` unique = idempotent with the source event (DMS Risk #9); `ReconciliationService` nightly vs PSP (R6).
- `payment.captured/settled/refunded` events → Booking, Notifications, Timeline, Reporting.

**Django concepts learned**
- The idempotency-key pattern in the data model — key + result stored in the same transaction as the state change.
- Double-entry accounting at the app layer — balanced posts, debit/credit single-side check, currency discipline (DDS §11 CHKs).
- Async worker flows for PSP calls and why the worker, not the request, owns the external round-trip (SDD §8.1).
- Adapter/interface pattern for external providers; contract tests against a sandbox.

**Review gate:** replay-returns-same-result tests, never-double-charge under worker-crash simulation, ledger-balance property test, nightly reconciliation mismatch surfacing.

---

### M11 — Allocation (`allocation`)

**Goal:** deterministic, audited physical room assignment at check-in (DR-11, FR-ALL-01/02).

**What we build**
- `allocation_record` (DDS §12) — the durable "why this room?" decision with criteria, scores, reason, override audit.
- `AllocationService` — pure scoring function (deterministic; AI additive in v3 with deterministic fallback), reading candidates via `RoomQuery` + housekeeping cleanliness + guest prefs through **selectors only** (DMS coupling rules).
- `room.allocated` event; wired into `CheckInOutService` (T6).

**Django concepts learned**
- Pure, testable domain functions (value objects in, decision out) — the foundation for A/B-ing the v3 AI variant.
- Selector composition across contexts without violating import rules (DMS dependency map).
- Stay-continuity bias and tie-breaking as explicit, audited rules.

**Review gate:** determinism test (same inputs → same room), override-is-audited test, never-allocates-OOO/OOS test.

---

### M12 — Housekeeping (`housekeeping`)

**Goal:** the nightly plan, task lifecycle, the readiness rule, and the defect loop (SDD §10.3, FR-HK-01/02/03).

**What we build**
- `hk_standard`, `hk_plan`, `housekeeping_task`, `inspection` (DDS §13).
- Night-audit job: departures → Vacant Dirty, in-house → Occupied Dirty (unless opted out), plan generated from occupancy (FR-HK-01).
- Task state machine on the substrate; `PlanGenerator`; defect → `hk.defect_reported` → work order (v2) + room OOS.
- **Event consumer** for `booking.checked_in/checked_out` driving the plan — first real "consume, don't query the producer" pattern at scale.

**Django concepts learned**
- Event consumers — the discipline of reacting without touching producer tables (coupling rule #2); idempotent consumption.
- Batched generation jobs (night audit) and avoiding N+1 in the plan generator (DDS D.1).
- The readiness invariant: `VD → Vacant Clean` only via `Cleaning → Inspected` — enforced by the workflow + room machine interplay.

**Review gate:** plan-generation correctness (departures/arrivals/in-house), task state matrix, defect → OOS → work-order flow.

---

### M13 — Notifications (`notifications`)

**Goal:** reliable multi-channel delivery via the outbox — no lost confirmation emails (DR-08, FR-NOT-01/02/04).

**What we build**
- `notification_job`, `delivery_attempt`, `notification_template`, `channel_preference` (DDS §19).
- The outbox relay consumer: event → resolve template (type/channel/locale) + channel preference → deliver → retry with backoff → dead-letter with alerting.
- Consent gating read from Guest Profile (eligibility) and channel preference (delivery) — two distinct reads, two owners (DMS Risk #5).
- Provider adapters (email/SMS/push/WhatsApp) behind `integrations`.

**Django concepts learned**
- The outbox **consumer** side (M1 built the producer side) — exactly-once-ish delivery via idempotent jobs.
- Retry/backoff/DLQ as data (attempt counts, states) — observability over silent loss.
- Template resolution as a cached `(tenant, type, channel, locale)` unique lookup.

**Review gate:** no-lost-notification test (crash between send and ack), no-duplicate-on-replay test, consent-gating test.

---

### M14 — Reviews + Timeline (`reviews`, `timeline`)

**Goal:** the review loop and the guest/stay timeline — both read-model/projection-heavy, both idempotent consumers (SDD §11.8, FR-TIM-01).

**What we build**
- `review`, `review_response` (DDS §17); `timeline_entry` (partitioned, DDS §18) with `(tenant_id, source_event_id)` unique for idempotency.
- `ReviewService` solicitation (T+24h after checkout, configurable), `TimelineProjector` consuming the event catalog, `TimelineService` reads (staff v1; guest v2).
- `projection_state` checkpointing — resume exactly-once, full-rebuild for recovery.

**Django concepts learned**
- Read models vs aggregates; why a projection has no write aggregates (DMS §18).
- Idempotent projection from a unique source-event constraint; partition-pruned reads.
- Scheduled solicitation via Celery beat.

**Review gate:** replay-no-duplicate test, rebuild-from-scratch test, timeline-per-stay + per-guest reads.

---

### M15 — Reporting + Search (`reporting`, `search`)

**Goal:** the KPI floor (occupancy/ADR/RevPAR snapshots) and candidate discovery via OpenSearch — both projections, both rebuildable (DR-12, FR-RPT-05, FR-SCH-01).

**What we build**
- `metric_snapshot` (committed nightly, idempotent per property/date), `report_definition`, `export_job` (DDS §20).
- Night-audit snapshot task (T13); OLAP copy/ETL seam.
- OpenSearch projection fed by events; `SearchService` pipeline: candidate discovery → **Availability filter** → **Pricing** → sort (SDD §11.5, DDS D.1).
- Index-as-disposable runbook; `projection_state` for search.

**Django concepts learned**
- Committed snapshots as immutable floor truth; reporting never touches the OLTP path (R11).
- External-index integration as a projection; eventual consistency acceptable *only* for discovery (DR-12).
- ETL/OLAP separation — the warehouse is a copy, never the source.

**Review gate:** snapshot idempotency + immutability, search pipeline correctness (never shows oversellable or mis-priced candidates), full-reindex runbook test.

---

### M16 — v1 Hardening & exit criteria

**Goal:** meet the SDD v1 exit criteria and the NFRs — degraded mode, second approval, RLS audit, race load test.

**What we build**
- **Degraded mode:** front desk books with `payment_pending`, capture later (R14) — payment coupling is policy-driven, never hard-coded.
- **Second approval / break-glass:** sensitive refunds, cancellation overrides, policy edits, role changes (SDD §14).
- **Cross-tenant RLS audit tests** across every table incl. ledger/audit/timeline (DMS Risk #11).
- **Load test of the oversell race** (two workers, one unit) and of the p95 booking-commit budget (< 1 s incl. payment trigger, SDD §5).
- Ops SLIs wired: booking success, payment success, job lag, **hold-expiry lag**, **projection lag** (SDD §5 Observability).

**Django concepts learned**
- Putting the concepts together as hardening: transaction scopes, idempotency seams, monitoring hooks — the difference between a demo and a production system.

**Review gate:** the full v1 exit criteria checklist (SDD §1.3) as an integration test suite, run against Dockerized infra.

---

### M17 — v2 scope

**Goal:** operate-like-a-pro (SDD §1.3). Maintenance, Guest Services, Loyalty, coupons/promotions, rule-based dynamic pricing, group/block pick-up, guest-facing timeline, digital-key hooks, AI concierge adapter.
- New tables from DDS: `work_order`, `work_order_task`, `part_usage`, `asset`, `service_request`, `staff_response`, `service_type`, `loyalty_account` + promotions structures.
- Concepts added: no-show processing as the first **process manager / saga** (SDD §8.2.1, DMS Risk #10), consumer scaling, rule-based pricing as data, group pick-up transactions, provider adapters (lock integrations, LLM).

### M18 — v3 scope

**Goal:** distribute everywhere (SDD §1.3). OTA integrations, channel manager (availability + rate sync via the `channel_allocation` seam — where DR-03 pays off), revenue management/forecasting, rate parity, virtual credit cards, enterprise SSO (OIDC/SAML), hardened residency.
- Concepts added: webhook security + signature verification, external sync idempotency, SSO flows, VCC lifecycle, multi-region tenant pinning.

---

## 5. Engineering practices (applied in every milestone)

1. **Teach before code.** Every new Django concept is explained before it is written — what it is, why it exists, what problem it solves, and when *not* to use it.
2. **Test pyramid.** Unit tests for value objects, workflows, services (with fakes); integration tests against Postgres (containers); API tests via DRF's test client. `pytest` + `factory_boy` throughout. Coverage gates per milestone.
3. **Migration discipline.** One migration per logical change; migrations are reviewed like code; `RunSQL` is isolated and documented (E7); never edit an applied migration.
4. **Review gate before every next milestone.** Self-review (concept intent vs implementation), a code review pass (correctness, invariants, N+1, RLS coverage), and a short retro. `MUST` block moving on until green.
5. **Repo discipline.** Commits are small and conventional; the docs (SDD/DMS/DDS/roadmap) stay in lockstep — any design deviation is a discussed document change, not a silent code drift.
6. **No premature abstraction.** The repository pattern is applied only where invariants demand it (E6); selectors + managers cover the rest. We add layers when a real second consumer appears, not in anticipation.
7. **Observability from M1.** Events, audit, and SLI hooks are part of the first milestone, not a retrofit.

---

## 6. Definition of done for v1 (the roadmap's end-of-phase checkpoint)

From SDD §1.3, verified as an automated integration suite:

> A 60-room hotel onboards; guests search and book direct; rooms are allocated at check-in; housekeeping runs; payments settle under policy; the receptionist sees a guest timeline; management sees occupancy/ADR/RevPAR — with no other tool.

Plus the NFRs: no overselling under race, RPO ≤ 15 min / RTO ≤ 1 h, cross-tenant isolation proven, idempotent money and bookings, degraded mode during PSP outage.

---

*End of Implementation Roadmap v1.0. Milestones M0–M16 constitute v1; M17–M18 are the v2/v3 phases. Each milestone is one bounded-context step, gated by review.*
