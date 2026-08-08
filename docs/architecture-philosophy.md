# Architecture Philosophy (M1 retrospective — permanent sections)

These two sections are **permanent**: every future milestone retrospective (M2, M3, …)
must include them, using the accumulated examples from that milestone. They join the
other permanent M1 lessons — the layered responsibility model, the decision framework,
and the mental checklist — as the lens through which the whole platform is read.

> The M1 through-line they all enforce: **facts go down, choices stay up.**
> Universal structure lives as deep as it must be to be inescapable; business
> meaning stays in the service. Mechanism in the kernel, policy in the context.

---

## 1. Architectural Anti-patterns

These are *design* mistakes — misplacement of responsibility, not bad code. Each one
violates the M1 philosophy at a specific layer. Learn to recognize the symptom; the
fix is always "move the rule to the layer that can hold it."

### 1.1 Making a value object into a model
- **The mistake:** giving an identity-less value an identity — a `Money` table, a `StayPeriod` row.
- **Why it violates the philosophy:** value semantics die. Two `Money(90000, NGN)` become distinguishable rows; equality-by-value becomes a dereference; the DB fills with meaningless rows.
- **Symptom:** "Should we store the amount as its own model?" — the answer is always no.
- **The fix:** primitives in columns, value objects reconstructed at the service boundary.

### 1.2 Putting business policy into a value object
- **The mistake:** a value object grows context-specific rules — `Address` validating Nigerian postal formats, `PhoneNumber` doing region lookup.
- **Why it violates the philosophy:** the kernel is imported everywhere, so one context's policy leaks into every context. The kernel/context boundary is the platform's spine.
- **Symptom:** a value object whose docstring names a bounded context, or whose tests assert business rules.
- **The fix:** mechanism in the value object, policy in the owning context.

### 1.3 Putting business orchestration into `save()`
- **The mistake:** `save()` sends notifications, decrements inventory, runs the workflow.
- **Why it violates the philosophy:** `save()` is a *persistence primitive*, called by forms, serializers, fixtures and bulk paths in different ways. Logic there runs on partial saves, double-fires, and is untestable in isolation. (`save()`-level *persistence semantics* — the version guard, auto_now — are legitimate; *orchestration* is not.)
- **Symptom:** "why does creating a Booking send an email?" — because the engineer saved.
- **The fix:** orchestration lives in the service; the transaction owns atomicity; `on_commit`/outbox own side effects.

### 1.4 Relying on forms instead of constraints
- **The mistake:** trusting `choices=` / `clean()` to protect the database.
- **Why it violates the philosophy:** forms are bypassable — `create()`, `bulk_create()`, raw SQL and imports never run them. The closed set is only real when the schema enforces it.
- **Symptom:** the `NoConstraintProbe` control — `create(status="half-occupied")` silently succeeds.
- **The fix:** form validation for UX, `CheckConstraint` for truth. Both, not either.

### 1.5 Using transactions to compensate for missing validation
- **The mistake:** wrapping everything in `atomic` and rolling back on exceptions, instead of rejecting the bad input up front.
- **Why it violates the philosophy:** transactions guarantee *durability*, never *correctness* — they happily commit two invalid rows. Compensating rolls back *after* the work, wastes resources, and hides the real error behind a generic rollback.
- **Symptom:** "it's fine, the transaction will catch it" — a sign the rule lives at the wrong layer.
- **The fix:** validate where the failure should surface (value objects, constraints), and transact the *workflow*.

### 1.6 Putting orchestration into PostgreSQL
- **The mistake:** stored procedures running workflows, business decisions in triggers.
- **Why it violates the philosophy:** the DB is the referee, not the decision-maker. Business meaning belongs in the service where it is testable, versionable and visible; procedural DB logic is none of those. (RLS is legitimate — a security *fact*, not a workflow.)
- **Symptom:** a stored procedure whose name describes a use case ("confirm_booking_and_email").
- **The fix:** PostgreSQL enforces facts; services make choices; the transaction coordinates.

### 1.7 Storing derived state
- **The mistake:** persisting `nights`, `total_guests`, or a running balance when they can be computed from irreducible primitives.
- **Why it violates the philosophy:** two sources of truth drift — the M1.1 derived-properties lesson. Computation is the single source of truth.
- **Symptom:** a field that must be kept "in sync" with other fields.
- **The fix:** derive in the value object; store only what cannot be recomputed.

### 1.8 Schema the model doesn't know
- **The mistake:** hand-writing `CREATE INDEX` / constraints / raw DDL in a migration without declaring them on the model.
- **Why it violates the philosophy:** `makemigrations` can't diff what it can't see, so the model and the schema drift and environments diverge.
- **Symptom:** "that index only exists in production."
- **The fix:** declare intent in `Meta.indexes`/`Meta.constraints`; let migrations realize it; reserve `RunSQL` for what is genuinely inexpressible, written reversibly.

### 1.9 Reimplementing framework guarantees
- **The mistake:** hand-rolled optimistic locking per context, manual `on_commit`, `obj.field += 1` for counters.
- **Why it violates the philosophy:** every reimplementation is a fork that can drift and be wrong; the kernel owns each mechanism exactly once so it cannot be forgotten.
- **Symptom:** three contexts with three subtly different versions of "the same" pattern.
- **The fix:** the shared helper (`conditional_update`, `VersionedMixin`, `status_constraint`) is the single implementation.

### The recognition rule
If you can name the anti-pattern, you already know the fix. Most appear because a rule was
placed where it was *convenient* rather than where it was *held*. Ask: **"If every writer
that could bypass this layer showed up today, would the rule still hold?"** If not, it lives
too high.

---

## 2. How an experienced Django engineer thinks

Given a feature request, the decomposition is a **fixed skeleton with iterative deepening** —
never linear, always the same shape. The engineer starts with the *domain language*, not the
models, and works down to persistence, then back up to orchestration.

```
Feature
  ↓
1. Value Objects        "what domain language does this speak?"
  ↓
2. Entities             "what persisted things change?"
  ↓
3. Persistence concerns "what facts must the database hold?"
  ↓
4. Transactions         "which writes are one atomic unit?"
  ↓
5. Optimistic locking   "which rows race between writers?"
  ↓
6. External side effects"what must fire only after commit?"
  ↓
7. Services             "which decisions are the workflow's own?"
```

### The questions at each stage

1. **Value Objects** — What domain language does the feature speak? What must never be born
   invalid? (A refund is `Money`, currency-checked, never a float; a stay is a `StayPeriod`.)
2. **Entities** — What persisted things change? Do new entities inherit `EntityMixin`? Does an
   existing entity gain a status, or is a new entity warranted for the audit trail?
3. **Persistence concerns** — Which facts must the database enforce against *every* writer?
   Closed status sets (constraint recipe), non-negativity, referential integrity, hot-subset
   indexes. What would a raw SQL import corrupt?
4. **Transactions** — Which writes must move together? *"If write #2 of 3 fails, would write #1
   being committed be a lie?"* If yes, wrap them in one `atomic`.
5. **Optimistic locking** — Which single rows race between writers? Guard with `version` /
   `conditional_update`; a `0`-rows result is a lost race and a decision point, not a failure.
6. **External side effects** — Which notifications/emails/relays must never fire for data that
   didn't commit? Defer them with `on_commit` or the outbox.
7. **Services** — Which decisions belong to the workflow itself? Which tenant, how to
   reconstruct value objects from columns, what a `ConcurrencyError` means to the user, whether
   to retry.

### Worked example — "A guest cancels a confirmed booking; the platform auto-refunds and notifies."

1. **Value Objects:** the refund is `Money` (currency-checked arithmetic, never a float); the
   stay being cancelled is a `StayPeriod`; the actors are `GuestId`, `PropertyId`, `BookingId`.
   Nothing here can be born invalid.
2. **Entities:** `Booking` changes state (already `EntityMixin`); `Payment` changes state or a
   new `Refund` row records the trail — inheriting `EntityMixin` for stamps/tenant/version.
3. **Persistence:** `BookingStatus` is a closed set → `status_constraint`; a refund only makes
   sense against a cancelled booking → the constraint *and* a service check (the constraint
   holds the shape, the service holds the meaning).
4. **Transactions:** the booking state change + the refund row + the ledger effect are ONE
   `atomic` — a half-refund would be a lie, so a failure rolls all of them back.
5. **Optimistic locking:** two agents cancelling the same booking race — `conditional_update`
   with `version`; the loser's `0` rows means "already cancelled" → idempotent, not an error.
6. **External side effects:** the guest email fires only after commit, via `on_commit` →
   the outbox (M1.3). The relay only ever sees committed state.
7. **Services:** the orchestration — build the `Money`/`StayPeriod` from input, load the
   entities, run the guarded updates, interpret `0` rows, register the `on_commit` side effect.
   Decisions (which tenant, recovery copy) live here.

### What the experienced engineer does NOT do first
- Does not open the models file first.
- Does not write a migration first.
- Does not start with the serializer or the view.
- Thinks in the feature's domain language first; the layers then fall into place.
The skeleton is the same every time — the skill is in *where the rule belongs*, and the
anti-patterns above are precisely the mistakes that appear when the skeleton is skipped.
