# Frontend Architecture

This document covers the Angular frontend only. It does not modify or supersede the backend design record (`software-design-document.md`, `domain-model-specification.md`, `architecture-philosophy.md`) — the backend remains the single source of business truth, and nothing here describes business rules, only how the client consumes them.

The frontend was built in milestones (A0–A7) against the backend's real, already-frozen HTTP contract: A0 established a thin API surface directly mirroring each backend app's service/query layer, A1 built the shell and session-cookie authentication, A2–A6 each added one operational area (Availability/Reservations, Bookings/Guests, Rooms/Allocation, Housekeeping, Notifications/Dashboard), and A7 was a hardening pass — accessibility, responsiveness, dead-code removal, and end-to-end verification, with no new features.

## Structure

```
src/app/
  core/           # app-wide infrastructure — one of each, used everywhere
    api/          # tenant + auth API services shared across the shell
    auth/         # AuthService, route guards
    http/         # interceptors: CSRF, tenant header, credentials, error normalization
    layout/       # Shell (toolbar/sidenav/router-outlet), nav item list
    tenant/       # TenantService (tenant list + selection)
  shared/         # reusable, feature-agnostic building blocks
    models/       # ApiError + shared domain-adjacent types (User, Tenant, Membership)
    ui/           # EmptyState, LoadingIndicator, ToastService
    utils/        # generateIdempotencyKey()
  features/<domain>/
    models/       # TypeScript interfaces matching each backend serializer exactly
    api/          # one thin HttpClient wrapper per backend app — no logic
    store/        # signal-based state for that feature
    components/   # small reusable pieces (e.g. status badges)
    pages/        # routed components
    <domain>.routes.ts
```

Fourteen feature areas: `allocation`, `availability`, `bookings`, `dashboard`, `guests`, `housekeeping`, `login`, `notifications`, `reservations`, `rooms`, plus `placeholder` (a minimal stub component kept only as a lightweight route double in `error.interceptor.spec.ts` — it is not wired into any production route).

## State management

Signals only — no NgRx, no global business-state store. Each feature Store is a `providedIn: 'root'` singleton holding that feature's own state as plain `signal()`s, with `computed()` for anything derived. The recurring shape, established in A2 and repeated through A6:

```ts
readonly list = signal<T[]>([]);
readonly listLoading = signal(false);
readonly listError = signal<ApiError | null>(null);

readonly current = signal<T | null>(null);
readonly detailLoading = signal(false);
readonly detailError = signal<ApiError | null>(null);
```

List and detail state are kept in separate signal pairs deliberately, so a detail-page mutation never has to reason about (or accidentally clobber) list-page state and vice versa.

**Every mutation replaces state only from the server's response.** No Store computes a resulting status, room state, or task state locally — a `startCleaning()` call, for example, does nothing to `current` until the backend's response for that exact call arrives, and on failure `current` is left untouched while the backend's own error message is surfaced. This is the direct frontend expression of the backend being the single source of truth: the UI is a rendering of server state, never a second copy of it.

`DashboardStore` is the one Store that composes multiple feature API services directly (`ReservationApiService`, `BookingApiService`, `RoomApiService`, `HousekeepingApiService`, `NotificationApiService`) rather than depending on the other feature Stores — this keeps the five dashboard panels loading in parallel and failing independently (one panel's error never blanks the others), and avoids coupling Dashboard's lifecycle to five other features' Store lifecycles. There is no `/api/dashboard/` endpoint; the dashboard is purely a client-side composition of existing read endpoints.

## API communication

One `HttpClient` wrapper per backend app (e.g. `ReservationApiService`, `RoomApiService`), each exposing exactly the endpoints that app's `api/` package supports — never more. No service performs business logic, computes a status, or transforms a domain shape; each method is a direct `get`/`post` call returning the backend's own response type.

Four HTTP interceptors, applied to every request whose URL starts with the configured API base:

| Interceptor | Responsibility |
|---|---|
| `withCredentialsInterceptor` | attaches `withCredentials: true` so session/CSRF cookies travel cross-origin |
| `csrfInterceptor` | echoes the `csrftoken` cookie back as `X-CSRFToken` on unsafe methods |
| `tenantInterceptor` | attaches `X-Tenant-Id` from `TenantService.selectedTenantId()` |
| `errorInterceptor` | normalizes every failure into `ApiError`, redirects to `/login` on a genuine session-expiry 401, toasts infrastructure-level failures (0/5xx/429) |

Business errors (400/403/404/409) are deliberately left for the calling component/Store to render — the interceptor never replaces a useful backend message with a generic one.

## Authentication

Session-cookie authentication, matching the backend exactly — there is no token of any kind. `AuthService` holds the current user as a signal, populated from `GET /api/auth/me/` on bootstrap. No authentication data is ever written to `localStorage` or `sessionStorage`.

## Tenant selection

`TenantService` holds the user's tenant memberships and the selected tenant id. For a single-membership user the tenant is auto-selected; a multi-membership user is gated behind an explicit selection (`Shell`'s `.tenant-gate`) until they pick one. The selected tenant id is the *only* thing persisted client-side, and only in `sessionStorage` (cleared with the tab).

Switching tenants (the toolbar dropdown) triggers a full page reload rather than an in-place state refresh. This is deliberate: every feature Store is a root-provided singleton holding the previously-selected tenant's already-loaded data, and switching tenants doesn't change the current route, so the router has no natural trigger to reload it. A full reload is the simplest way to guarantee no tenant's data is ever left visible once another tenant is selected — found as a real gap during the A7 hardening pass and fixed there, verified against a real two-tenant user end-to-end.

## Routing

Lazy-loaded throughout (`loadComponent`/`loadChildren`), one chunk per feature. `/dashboard` is the default route (`''` redirects to it). Every route in the approved tree resolves to a real component — no placeholder remains in `app.routes.ts` as of A6.

## Feature boundaries

A feature's Store/API/models are private to that feature; other features reach in only through **routing** (a `routerLink` to `/bookings/:id`) or, in `DashboardStore`'s case, through another feature's **API service** (never its Store, and never its models beyond the read-only shape returned by that API). No feature mutates another feature's state, and no feature re-implements another feature's domain logic.

## Error handling

A single normalized shape, `ApiError { status, message, raw }` (`shared/models/api-error.model.ts`), produced by `fromHttpError()`/`toApiError()` and used identically by every Store. `message` folds both of the backend's real error shapes (`{detail: string}` and DRF's `{field: [messages]}`) into one string, with an appropriate fallback per HTTP status when the body has neither. This is the only place error-message extraction happens — no feature re-implements it.

## Testing strategy

- **Unit/component (Vitest, via `@angular/build:unit-test`)**: every Store and every page component has a spec covering its success path, loading state, empty state, and error state; mutation specs assert the *absence* of optimistic/local state changes on failure. 247 specs across 37 files as of the final hardening pass.
- **Routing**: `app.routes.spec.ts` exercises guard behavior (unauthenticated redirect, authenticated `/login` redirect, unknown-path fallback) and confirms every route in the tree resolves.
- **Real-browser (Playwright, used transiently per milestone — not a committed dependency)**: every milestone's UI was verified against the live Django backend with real seeded data, never mocked. The final hardening pass added one committed-in-spirit (run, then removed as scratch tooling) critical end-to-end journey — availability search through reservation, booking, allocation, checkout, housekeeping, inspection, dashboard, and notifications — and a negative-path run covering session expiry, concurrent 409s on booking confirmation/allocation/housekeeping, and tenant-switch isolation.
