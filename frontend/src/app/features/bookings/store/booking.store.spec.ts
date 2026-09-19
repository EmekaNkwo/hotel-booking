import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { BookingStore } from './booking.store';
import { Booking } from '../models/booking.model';
import { environment } from '../../../../environments/environment';

const BOOKING: Booking = {
  id: 1, booking_ref: 'BR1', aggregate_status: 'pending_payment', currency: 'NGN',
  total_minor_units: 20000, arrival_date: '2026-10-01', departure_date: '2026-10-03',
  guest_profile_id: 1, reservation_id: 5, guest_snapshot: { email: 'g@example.com' },
  lines: [], created_at: '2026-09-01T00:00:00Z',
};

describe('BookingStore', () => {
  let store: BookingStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(BookingStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('loadList() populates the list from the server', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/bookings/?page=1`)
      .flush({ count: 1, next: null, previous: null, results: [BOOKING] });
    await promise;
    expect(store.list().length).toBe(1);
    expect(store.list()[0].booking_ref).toBe('BR1');
  });

  it('loadList() failure clears the list and sets listError', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/bookings/?page=1`)
      .flush({ detail: 'nope' }, { status: 403, statusText: 'Forbidden' });
    await promise;
    expect(store.list()).toEqual([]);
    expect(store.listError()?.message).toBe('nope');
  });

  it('loadOne() populates current from the authoritative detail response', async () => {
    const promise = store.loadOne(1);
    httpMock.expectOne(`${environment.apiBaseUrl}/bookings/1/`).flush(BOOKING);
    await promise;
    expect(store.current()?.booking_ref).toBe('BR1');
  });

  it('confirm() success replaces current with the returned Booking (never assumed locally)', async () => {
    const promise = store.confirm({ reservation_id: 5, idempotency_key: 'k1' });

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/bookings/confirm/`);
    expect(req.request.body).toEqual({ reservation_id: 5, idempotency_key: 'k1' });
    req.flush(BOOKING, { status: 201, statusText: 'Created' });

    const result = await promise;
    expect(result?.booking_ref).toBe('BR1');
    expect(store.current()?.aggregate_status).toBe('pending_payment');
  });

  it('confirm() 409 does not set current and surfaces the backend message', async () => {
    const promise = store.confirm({ reservation_id: 5, idempotency_key: 'k1' });

    httpMock
      .expectOne(`${environment.apiBaseUrl}/bookings/confirm/`)
      .flush({ detail: 'reservation is not awaiting payment.' }, { status: 409, statusText: 'Conflict' });

    const result = await promise;
    expect(result).toBeNull();
    expect(store.current()).toBeNull();
    expect(store.error()?.status).toBe(409);
    expect(store.error()?.message).toBe('reservation is not awaiting payment.');
  });

  it('confirm() loading state toggles around the request', async () => {
    const promise = store.confirm({ reservation_id: 5 });
    expect(store.loading()).toBe(true);
    httpMock.expectOne(`${environment.apiBaseUrl}/bookings/confirm/`).flush(BOOKING, { status: 201, statusText: 'Created' });
    await promise;
    expect(store.loading()).toBe(false);
  });

  it('clearCurrent() resets current and error', async () => {
    const promise = store.loadOne(1);
    httpMock.expectOne(`${environment.apiBaseUrl}/bookings/1/`).flush(BOOKING);
    await promise;

    store.clearCurrent();

    expect(store.current()).toBeNull();
    expect(store.error()).toBeNull();
  });

  describe('R0.10: out-of-order responses', () => {
    const BOOKING_2: Booking = { ...BOOKING, id: 2, booking_ref: 'BR2' };

    it('loadOne(5) then loadOne(6): a late-resolving response for 5 must not overwrite 6 (simulates navigating away mid-request)', async () => {
      const first = store.loadOne(1); // "booking 5" stand-in
      const firstReq = httpMock.expectOne(`${environment.apiBaseUrl}/bookings/1/`);

      const second = store.loadOne(2); // navigated to "booking 6" before the first resolved
      const secondReq = httpMock.expectOne(`${environment.apiBaseUrl}/bookings/2/`);

      // Second request resolves FIRST...
      secondReq.flush(BOOKING_2);
      await second;
      expect(store.current()?.id).toBe(2);

      // ...then the stale first request finally resolves — must be ignored.
      firstReq.flush(BOOKING);
      await first;
      expect(store.current()?.id).toBe(2);
    });

    it('loadList() called twice: only the LATEST call\'s result is applied, regardless of resolution order', async () => {
      const first = store.loadList();
      const firstReq = httpMock.expectOne(`${environment.apiBaseUrl}/bookings/?page=1`);

      const second = store.loadList();
      const secondReq = httpMock.expectOne(`${environment.apiBaseUrl}/bookings/?page=1`);

      secondReq.flush({ count: 1, next: null, previous: null, results: [BOOKING_2] });
      await second;
      expect(store.list()).toEqual([BOOKING_2]);

      firstReq.flush({ count: 1, next: null, previous: null, results: [BOOKING] });
      await first;
      expect(store.list()).toEqual([BOOKING_2]); // the stale first call never applied
    });

    it('loadOne() and confirm() share one guard on `current`: a late loadOne() cannot stomp a newer confirm() result', async () => {
      const loadPromise = store.loadOne(1);
      const loadReq = httpMock.expectOne(`${environment.apiBaseUrl}/bookings/1/`);

      const confirmPromise = store.confirm({ reservation_id: 5, idempotency_key: 'k1' });
      const confirmReq = httpMock.expectOne(`${environment.apiBaseUrl}/bookings/confirm/`);

      // confirm() resolves first — it's the newer call, so it wins.
      confirmReq.flush(BOOKING_2, { status: 201, statusText: 'Created' });
      await confirmPromise;
      expect(store.current()?.id).toBe(2);

      // The stale loadOne() resolves after — must not overwrite it.
      loadReq.flush(BOOKING);
      await loadPromise;
      expect(store.current()?.id).toBe(2);
    });
  });

  describe('R1.1: pagination', () => {
    it('nextPage()/previousPage() replace the list per page and track count/flags from the server', async () => {
      const load1 = store.loadList();
      httpMock.expectOne(`${environment.apiBaseUrl}/bookings/?page=1`).flush({
        count: 30, next: 'http://x/bookings/?page=2', previous: null, results: [BOOKING],
      });
      await load1;
      expect(store.hasNextPage()).toBe(true);
      expect(store.hasPreviousPage()).toBe(false);

      const load2 = store.nextPage();
      httpMock.expectOne(`${environment.apiBaseUrl}/bookings/?page=2`).flush({
        count: 30, next: null, previous: 'http://x/bookings/?page=1', results: [{ ...BOOKING, id: 2 }],
      });
      await load2;
      expect(store.currentPage()).toBe(2);
      expect(store.list()).toEqual([{ ...BOOKING, id: 2 }]); // replaces, never appends
      expect(store.hasNextPage()).toBe(false);
    });

    it('nextPage() is a no-op once the server reports no next page', async () => {
      const load1 = store.loadList();
      httpMock
        .expectOne(`${environment.apiBaseUrl}/bookings/?page=1`)
        .flush({ count: 1, next: null, previous: null, results: [BOOKING] });
      await load1;
      await store.nextPage();
      httpMock.expectNone(`${environment.apiBaseUrl}/bookings/?page=2`);
    });
  });
});
