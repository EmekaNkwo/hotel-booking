import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { ReservationStore } from './reservation.store';
import { Reservation } from '../models/reservation.model';
import { environment } from '../../../../environments/environment';

const RESERVATION: Reservation = {
  id: 1, reservation_ref: 'ABC123', status: 'held', channel: 'direct', hold_expiry_at: '2026-10-01T00:00:00Z',
  price_snapshot: {}, policy_snapshot: {}, guest_profile_id: 1, property_id: 1, lines: [], created_at: '2026-09-01T00:00:00Z',
};

describe('ReservationStore', () => {
  let store: ReservationStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(ReservationStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('create() success sets current from the server response (never a local guess)', async () => {
    const promise = store.create({
      property_id: 1, guest_email: 'g@example.com',
      lines: [{ room_type_id: 1, arrival_date: '2026-10-01', departure_date: '2026-10-03', adults: 2, children: 0, quantity: 1 }],
    });

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/reservations/`);
    expect(req.request.method).toBe('POST');
    req.flush(RESERVATION, { status: 201, statusText: 'Created' });

    const result = await promise;
    expect(result?.status).toBe('held');
    expect(store.current()?.status).toBe('held');
  });

  it('create() never sets a status locally on failure — current stays null and error is populated', async () => {
    const promise = store.create({
      property_id: 1, lines: [{ room_type_id: 1, arrival_date: '2026-10-01', departure_date: '2026-10-03', adults: 1, children: 0, quantity: 999 }],
    });

    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/`)
      .flush({ detail: 'insufficient availability.' }, { status: 409, statusText: 'Conflict' });

    const result = await promise;
    expect(result).toBeNull();
    expect(store.current()).toBeNull();
    expect(store.error()?.status).toBe(409);
    expect(store.error()?.message).toBe('insufficient availability.');
  });

  it('loadOne() populates current from the authoritative detail response', async () => {
    const promise = store.loadOne(1);
    httpMock.expectOne(`${environment.apiBaseUrl}/reservations/1/`).flush(RESERVATION);
    await promise;
    expect(store.current()?.reservation_ref).toBe('ABC123');
  });

  it('requestPayment() replaces current with the returned reservation state', async () => {
    store.current.set(RESERVATION);
    const promise = store.requestPayment(1);

    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/1/request-payment/`)
      .flush({ ...RESERVATION, status: 'awaiting_payment' });

    const ok = await promise;
    expect(ok).toBe(true);
    expect(store.current()?.status).toBe('awaiting_payment');
  });

  it('requestPayment() 409 leaves the stale status untouched and surfaces the backend message', async () => {
    store.current.set(RESERVATION);
    const promise = store.requestPayment(1);

    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/1/request-payment/`)
      .flush({ detail: 'reservation is not held.' }, { status: 409, statusText: 'Conflict' });

    const ok = await promise;
    expect(ok).toBe(false);
    expect(store.current()?.status).toBe('held'); // unchanged — no optimistic mutation
    expect(store.error()?.message).toBe('reservation is not held.');
  });

  it('cancel() replaces current with the returned cancelled state', async () => {
    store.current.set(RESERVATION);
    const promise = store.cancel(1, 'key-1');

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/reservations/1/cancel/`);
    expect(req.request.body).toEqual({ idempotency_key: 'key-1' });
    req.flush({ ...RESERVATION, status: 'cancelled' });

    const ok = await promise;
    expect(ok).toBe(true);
    expect(store.current()?.status).toBe('cancelled');
  });

  it('loadList() populates the list and pagination state from the server, replacing any prior list', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=1`)
      .flush({ count: 1, next: null, previous: null, results: [RESERVATION] });
    await promise;
    expect(store.list().length).toBe(1);
    expect(store.list()[0].reservation_ref).toBe('ABC123');
    expect(store.count()).toBe(1);
    expect(store.currentPage()).toBe(1);
    expect(store.hasNextPage()).toBe(false);
    expect(store.hasPreviousPage()).toBe(false);
  });

  it('loadList() failure clears the list and sets listError', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=1`)
      .flush({ detail: 'nope' }, { status: 403, statusText: 'Forbidden' });
    await promise;
    expect(store.list()).toEqual([]);
    expect(store.listError()?.message).toBe('nope');
  });

  it('nextPage()/previousPage() navigate using the authoritative next/previous flags and preserve the filter', async () => {
    const load1 = store.loadList('held');
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=1&status=held`)
      .flush({
        count: 30,
        next: 'http://x/reservations/?page=2&status=held',
        previous: null,
        results: [RESERVATION],
      });
    await load1;
    expect(store.hasNextPage()).toBe(true);

    const load2 = store.nextPage();
    const req2 = httpMock.expectOne(`${environment.apiBaseUrl}/reservations/?page=2&status=held`);
    req2.flush({
      count: 30,
      next: null,
      previous: 'http://x/reservations/?page=1&status=held',
      results: [{ ...RESERVATION, id: 2, reservation_ref: 'DEF456' }],
    });
    await load2;
    expect(store.currentPage()).toBe(2);
    expect(store.list()[0].reservation_ref).toBe('DEF456');
    expect(store.hasNextPage()).toBe(false);
    expect(store.hasPreviousPage()).toBe(true);

    // page data REPLACES the prior page, never appends
    expect(store.list().length).toBe(1);

    const load3 = store.previousPage();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=1&status=held`)
      .flush({
        count: 30,
        next: 'http://x/reservations/?page=2&status=held',
        previous: null,
        results: [RESERVATION],
      });
    await load3;
    expect(store.currentPage()).toBe(1);
    expect(store.list()[0].reservation_ref).toBe('ABC123');
  });

  it('nextPage() is a no-op when the server reports no next page', async () => {
    const load1 = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=1`)
      .flush({ count: 1, next: null, previous: null, results: [RESERVATION] });
    await load1;

    await store.nextPage();
    httpMock.expectNone(`${environment.apiBaseUrl}/reservations/?page=2`);
    expect(store.currentPage()).toBe(1);
  });

  it('loadList() called fresh (as applyFilters()/clearFilters() do) resets to page 1', async () => {
    const load1 = store.loadList(undefined, 1);
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=1`)
      .flush({
        count: 30,
        next: 'http://x/reservations/?page=2',
        previous: null,
        results: [RESERVATION],
      });
    await load1;

    const load2 = store.nextPage();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=2`)
      .flush({ count: 30, next: null, previous: 'http://x', results: [RESERVATION] });
    await load2;
    expect(store.currentPage()).toBe(2);

    // simulating a filter change: loadList() is called again without a page argument
    const load3 = store.loadList('cancelled');
    httpMock
      .expectOne(`${environment.apiBaseUrl}/reservations/?page=1&status=cancelled`)
      .flush({ count: 0, next: null, previous: null, results: [] });
    await load3;
    expect(store.currentPage()).toBe(1);
  });
});
