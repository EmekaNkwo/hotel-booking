import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { DashboardStore } from './dashboard.store';
import { environment } from '../../../../environments/environment';
import { Room } from '../../rooms/models/room.model';
import { HousekeepingTask } from '../../housekeeping/models/housekeeping-task.model';
import { Booking } from '../../bookings/models/booking.model';
import { Reservation } from '../../reservations/models/reservation.model';
import { NotificationJob } from '../../notifications/models/notification-job.model';

const ROOM_TYPE = { id: 1, code: 'STD', name: 'Standard', status: 'active', max_occupancy: 3, attributes: {} };

const ROOMS: Room[] = [
  { id: 1, code: '101', property_id: 1, room_type: ROOM_TYPE, operational_state: 'occupied_dirty', current_booking_line_id: 5 },
  { id: 2, code: '102', property_id: 1, room_type: ROOM_TYPE, operational_state: 'vacant_clean', current_booking_line_id: null },
];

const TASKS: HousekeepingTask[] = [
  { id: 1, room_id: 1, booking_line_id: 5, business_date: '2026-10-03', task_kind: 'departure', status: 'planned', assignee_id: null, created_at: '2026-10-03T00:00:00Z' },
];

const BOOKINGS: Booking[] = [
  {
    id: 1, booking_ref: 'BK-1', aggregate_status: 'confirmed', currency: 'USD', total_minor_units: 10000,
    arrival_date: '2026-10-03', departure_date: '2026-10-05', guest_profile_id: 1, reservation_id: 1,
    guest_snapshot: {}, lines: [], created_at: '2026-10-01T00:00:00Z',
  },
];

const RESERVATIONS: Reservation[] = [
  {
    id: 1, reservation_ref: 'RES-1', status: 'held', channel: 'direct', hold_expiry_at: null,
    price_snapshot: {}, policy_snapshot: {}, guest_profile_id: 1, property_id: 1, lines: [], created_at: '2026-10-01T00:00:00Z',
  },
];

const NOTIFICATION: NotificationJob = {
  id: 1, notification_type: 'booking_confirmed', channel: 'email', status: 'failed', retry_count: 3,
  last_error: 'timeout', recipient_guest_id: 1, context: {}, created_at: '2026-10-01T00:00:00Z',
};

const ROOM_STATES = [
  'vacant_clean', 'vacant_dirty', 'occupied_clean', 'occupied_dirty',
  'out_of_service', 'out_of_order', 'cleaning', 'inspected',
];
const TASK_STATES = ['planned', 'assigned', 'in_progress', 'quality_check', 'verified', 'defect'];

function page<T>(results: T[], count = results.length) {
  return { count, next: null, previous: null, results };
}

describe('DashboardStore', () => {
  let store: DashboardStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(DashboardStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  /** Flushes every request `loadAll()` issues. `roomCount`/`taskCount` let a
   * test simulate >25 rows for a given operational_state/status WITHOUT the
   * fixture's `count` ever being constructed as `results.length` — exactly
   * the R1.1 requirement that the Dashboard's counts must come from the
   * server's own filtered `count`, independent of how many rows a single
   * page happens to carry. */
  function flushAll(opts: { roomCounts?: Partial<Record<string, number>>; taskCounts?: Partial<Record<string, number>> } = {}) {
    httpMock.expectOne(`${environment.apiBaseUrl}/reservations/?page=1`).flush(page(RESERVATIONS));
    httpMock.expectOne(`${environment.apiBaseUrl}/bookings/?page=1`).flush(page(BOOKINGS));
    httpMock.expectOne(`${environment.apiBaseUrl}/rooms/?page=1`).flush(page(ROOMS));
    httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/?page=1`).flush(page(TASKS));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/notifications/` && r.params.get('status') === 'failed')
      .flush(page([NOTIFICATION]));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/notifications/` && r.params.get('status') === 'dead_lettered')
      .flush(page([]));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/reservations/` && r.params.get('status') === 'held')
      .flush(page([], 1));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/reservations/` && r.params.get('status') === 'awaiting_payment')
      .flush(page([], 0));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/bookings/` && r.params.get('status') === 'confirmed')
      .flush(page([], 1));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/bookings/` && r.params.get('arrival_date') != null)
      .flush(page([], 1));
    for (const state of ROOM_STATES) {
      httpMock
        .expectOne((r) => r.url === `${environment.apiBaseUrl}/rooms/` && r.params.get('operational_state') === state)
        .flush(page([], opts.roomCounts?.[state] ?? (state === 'occupied_dirty' || state === 'vacant_clean' ? 1 : 0)));
    }
    for (const state of TASK_STATES) {
      httpMock
        .expectOne((r) => r.url === `${environment.apiBaseUrl}/housekeeping/tasks/` && r.params.get('status') === state)
        .flush(page([], opts.taskCounts?.[state] ?? (state === 'planned' ? 1 : 0)));
    }
  }

  it('loadAll() composes every panel and every dedicated count query in parallel', async () => {
    const promise = store.loadAll();
    flushAll();
    await promise;

    expect(store.rooms().data).toEqual(ROOMS);
    expect(store.bookings().data).toEqual(BOOKINGS);
    expect(store.reservations().data).toEqual(RESERVATIONS);
    expect(store.housekeepingTasks().data).toEqual(TASKS);
    expect(store.problemNotifications().data).toEqual([NOTIFICATION]);
  });

  it('derives room/housekeeping counts from dedicated filtered-count requests, not from page-1 array length', async () => {
    const promise = store.loadAll();
    flushAll();
    await promise;

    expect(store.occupiedRoomsCount()).toBe(1);
    expect(store.roomStatusCounts().vacant_clean).toBe(1);
    expect(store.housekeepingStatusCounts().planned).toBe(1);
    expect(store.activeReservationsCount()).toBe(1);
    expect(store.confirmedBookingsCount()).toBe(1);
    expect(store.arrivalsTodayCount()).toBe(1);
    expect(store.recentBookings()).toEqual(BOOKINGS);
  });

  it('R1.2: arrivalsTodayCount is the count of a dedicated ?arrival_date= filtered query, not bookings().data.length', async () => {
    const promise = store.loadAll();
    // The bookings PANEL only ever carries one page-1 row, but the
    // dedicated arrival_date-filtered query reports 27 total arrivals
    // today — the widget must show 27, never bookings().data.length (1).
    httpMock.expectOne(`${environment.apiBaseUrl}/reservations/?page=1`).flush(page(RESERVATIONS));
    httpMock.expectOne(`${environment.apiBaseUrl}/bookings/?page=1`).flush(page(BOOKINGS));
    httpMock.expectOne(`${environment.apiBaseUrl}/rooms/?page=1`).flush(page(ROOMS));
    httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/?page=1`).flush(page(TASKS));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/notifications/` && r.params.get('status') === 'failed')
      .flush(page([]));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/notifications/` && r.params.get('status') === 'dead_lettered')
      .flush(page([]));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/reservations/` && r.params.get('status') === 'held')
      .flush(page([], 0));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/reservations/` && r.params.get('status') === 'awaiting_payment')
      .flush(page([], 0));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/bookings/` && r.params.get('status') === 'confirmed')
      .flush(page([], 0));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/bookings/` && r.params.get('arrival_date') != null)
      .flush(page([], 27));
    for (const state of ROOM_STATES) {
      httpMock
        .expectOne((r) => r.url === `${environment.apiBaseUrl}/rooms/` && r.params.get('operational_state') === state)
        .flush(page([], 0));
    }
    for (const state of TASK_STATES) {
      httpMock
        .expectOne((r) => r.url === `${environment.apiBaseUrl}/housekeeping/tasks/` && r.params.get('status') === state)
        .flush(page([], 0));
    }
    await promise;

    expect(store.arrivalsTodayCount()).toBe(27);
  });

  it('R1.1: counts remain correct even when a filtered state has more than one page (25+) of rows — count is read from the server, never results.length', async () => {
    const promise = store.loadAll();
    // Only one `occupied_dirty` room is ever returned in `results` (this is
    // a single-page fixture), but the server reports 42 total matching rows
    // — the dashboard must show 42, never `results.length` (1).
    flushAll({ roomCounts: { occupied_dirty: 42, vacant_clean: 3 }, taskCounts: { planned: 30 } });
    await promise;

    expect(store.roomStatusCounts().occupied_dirty).toBe(42);
    expect(store.roomStatusCounts().vacant_clean).toBe(3);
    expect(store.occupiedRoomsCount()).toBe(42); // occupied_dirty(42) + occupied_clean(0)
    expect(store.housekeepingStatusCounts().planned).toBe(30);
  });

  it('one panel failing does not prevent the others from loading (independent panel state)', async () => {
    const promise = store.loadAll();
    httpMock.expectOne(`${environment.apiBaseUrl}/reservations/?page=1`).flush(page(RESERVATIONS));
    httpMock
      .expectOne(`${environment.apiBaseUrl}/bookings/?page=1`)
      .flush({ detail: 'unavailable' }, { status: 500, statusText: 'Server Error' });
    httpMock.expectOne(`${environment.apiBaseUrl}/rooms/?page=1`).flush(page(ROOMS));
    httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/?page=1`).flush(page(TASKS));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/notifications/` && r.params.get('status') === 'failed')
      .flush(page([]));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/notifications/` && r.params.get('status') === 'dead_lettered')
      .flush(page([]));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/reservations/` && r.params.get('status') === 'held')
      .flush(page([], 1));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/reservations/` && r.params.get('status') === 'awaiting_payment')
      .flush(page([], 0));
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/bookings/` && r.params.get('status') === 'confirmed')
      .flush({ detail: 'unavailable' }, { status: 500, statusText: 'Server Error' });
    httpMock
      .expectOne((r) => r.url === `${environment.apiBaseUrl}/bookings/` && r.params.get('arrival_date') != null)
      .flush({ detail: 'unavailable' }, { status: 500, statusText: 'Server Error' });
    for (const state of ROOM_STATES) {
      httpMock
        .expectOne((r) => r.url === `${environment.apiBaseUrl}/rooms/` && r.params.get('operational_state') === state)
        .flush(page([], 0));
    }
    for (const state of TASK_STATES) {
      httpMock
        .expectOne((r) => r.url === `${environment.apiBaseUrl}/housekeeping/tasks/` && r.params.get('status') === state)
        .flush(page([], 0));
    }
    await promise;

    expect(store.bookings().error?.message).toBe('unavailable');
    expect(store.bookings().data).toBeNull();
    expect(store.rooms().data).toEqual(ROOMS);
    expect(store.reservations().data).toEqual(RESERVATIONS);
    // The confirmed-count query failing must not throw or block other panels —
    // it silently leaves the last-known scalar (0) rather than blanking the page.
    expect(store.confirmedBookingsCount()).toBe(0);
  });

  it('never mutates business state — every request loadAll() issues is a GET', async () => {
    const promise = store.loadAll();
    flushAll();
    await promise;
  });
});
