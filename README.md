# Hospitality Management Platform

A modular Django backend paired with an Angular staff-facing PMS (property management system) frontend — reservations, bookings, room allocation, housekeeping, and guest-notification delivery for a multi-tenant hotel operator.

This is a from-scratch engineering build: the backend was developed through a sequence of scoped milestones (M0–M13), each closing a bounded context with tests before the next began; the frontend followed the same discipline (A0–A7) against the backend's real, frozen HTTP contract. No milestone invented backend fields or endpoints the API didn't already expose, and no frontend milestone modified backend domain logic without an explicitly identified, narrowly-scoped blocker.

## What it is

A staff tool for running a hotel's day-to-day operations: search availability, take a reservation, confirm it into a booking, allocate a physical room, check the guest out, run the room through housekeeping, and see the result reflected on an operational dashboard — with delivery-status visibility into the notifications the system sends along the way. It is not a guest-facing booking site and does not process payments.

## Backend

A Django 5.2 / DRF, app-per-bounded-context modular monolith (PostgreSQL 16, Celery + Redis for async delivery), with each app owning its own models, services, and query layer:

- **Identity, Tenancy & RBAC** (`accounts`, `tenants`) — session-cookie authentication, MFA, tenant membership/roles, row-level tenant isolation
- **Properties & Rooms** (`properties`, `rooms`) — property/room-type/physical-room data and the room operational-state machine
- **Policies** (`policies`) — cancellation/rate policy snapshots
- **Guests** (`guests`) — guest profile identity and search
- **Pricing** (`pricing`) — rate plans and price computation feeding availability search
- **Availability & Inventory** (`availability`) — the anti-oversell sellable-inventory ledger
- **Reservations** (`reservations`) — the hold → awaiting-payment → converted lifecycle
- **Bookings** (`bookings`) — confirmed stays, immutable guest snapshot at confirmation time
- **Allocation** (`allocation`) — physical room assignment against confirmed booking lines
- **Housekeeping** (`housekeeping`) — the post-checkout cleaning/inspection task lifecycle
- **Notifications** (`notifications`) — event-triggered, Celery-delivered guest notifications with retry/dead-letter tracking

Business rules live in each app's service/query layer, never in views, serializers, or the database beyond structural constraints. See `docs/` for the full design record (software design document, domain model specification, and the accumulated architecture-philosophy retrospectives written during the backend build).

## Frontend

An Angular 22 application, built feature-by-feature against the backend's real API surface:

- Standalone components throughout — no NgModules
- Signal-based state (`signal`/`computed`) per feature Store — no NgRx, no global mega-store
- Angular Material 22 + CDK (M3 theming), a small shared component set (status badges, empty states, loading indicator)
- Lazy-loaded feature routes, one chunk per feature area
- Session-cookie authentication (no tokens in `localStorage`) with centralized CSRF header injection and tenant-header attachment via HTTP interceptors
- Zoneless change detection (`provideZonelessChangeDetection()`)

## Architecture

```
Angular (signals, standalone components)
   → thin per-feature HTTP/API services
   → Django REST Framework views (thin — no business logic)
   → application/domain services (apps/*/services.py)
   → PostgreSQL, with Celery/Redis for async notification delivery
```

The frontend is a consumer, not a decision-maker: every reservation/booking/allocation/housekeeping/notification/room status shown on screen is the backend's own response, rendered as-is. No workflow, state machine, or business rule is duplicated client-side — the frontend's job is to call the right endpoint, show the right authoritative result (success or the backend's own error message), and never assume an outcome it hasn't been told about. See `docs/frontend-architecture.md` for the detailed frontend design.

## Operational workflow (the demonstrated critical path)

```
Availability search
  → Reservation (held → awaiting payment)
  → Booking (confirmed)
  → Allocation (physical room assigned; room → occupied)
  → Checkout (housekeeping task created)
  → Housekeeping (start cleaning → complete cleaning → inspection)
  → Room → Vacant Clean
```

The Dashboard composes existing Reservations/Bookings/Rooms/Housekeeping/Notifications APIs into a single operational overview (no separate dashboard backend endpoint), and Notifications gives staff read-only visibility into delivery status, retries, and dead-lettered jobs for each guest-facing message the system has sent.

## Engineering characteristics

What was actually implemented and verified — not an aspirational list:

- **Tenant isolation**: every tenant-scoped request carries an `X-Tenant-Id` header attached centrally by an HTTP interceptor; the backend enforces isolation at the query layer. Verified end-to-end with a real two-tenant user: switching tenants clears all previously-loaded frontend state (a real gap found and fixed during the final hardening pass — see `docs/frontend-architecture.md`).
- **Idempotency**: state-changing commands (reservation cancel, booking confirm, allocation, checkout, housekeeping transitions) accept a client-generated idempotency key, generated once per user command and reused across retries of that exact command.
- **Optimistic concurrency**: version-guarded updates in the domain layer (see `docs/software-design-document.md`).
- **Pessimistic locking**: `SELECT ... FOR UPDATE` on the allocation hot path (candidate room selection) to prevent double-assignment under concurrent requests.
- **Transactional workflows**: multi-step domain operations (e.g., confirm-and-create-booking) are wrapped in a single atomic transaction; side effects (notifications) are dispatched via outbox/on-commit, never inside the transaction itself.
- **Authoritative backend state**: the frontend never computes or locally fabricates a status transition — it replaces its view of a resource only with what the server just returned.
- **API-level permissions**: session-cookie auth plus tenant-membership checks on every endpoint.
- **CSRF/session security**: Django's cookie/header CSRF contract, `withCredentials` centralized in one interceptor, no auth data ever written to `localStorage`.
- **Real-browser verification**: every milestone (frontend and final hardening pass) was verified with Playwright against the live Django backend and real seeded data — not mocked. A full critical-path run (availability → reservation → booking → allocation → checkout → housekeeping → inspection → dashboard → notifications) and a negative-path run (expired session, concurrent 409s on booking confirmation/allocation/housekeeping, tenant-switch isolation) both pass.

This is a portfolio/demonstration build, verified through the workflows and tests described above — it has not been deployed or load-tested in a production environment, and payment processing is explicitly out of scope.

## Getting started

**Backend**
```bash
cp .env.example .env   # fill in DJANGO_SECRET_KEY / MFA_FERNET_KEY (see comments in the file)
docker compose up -d   # Postgres + Redis
uv run python manage.py migrate
uv run python manage.py runserver 8000
```

**Frontend**
```bash
cd frontend
npm install
npm start               # serves on http://localhost:4200, proxying to the backend at :8000
```

**Tests**
```bash
uv run pytest                          # backend
cd frontend && npx ng test --watch=false   # frontend
```

## Documentation

- `docs/software-design-document.md`, `docs/domain-model-specification.md` — the backend's design record
- `docs/architecture-philosophy.md` — accumulated architectural decisions and anti-patterns from the backend build
- `docs/implementation-roadmap.md` — the milestone plan the backend was built against
- `docs/frontend-architecture.md` — the Angular frontend's structure, state management, and API/auth/tenant conventions
