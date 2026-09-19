import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { AvailabilityStore } from './availability.store';
import { environment } from '../../../../environments/environment';

const PARAMS = {
  property_id: 1,
  room_type_id: 1,
  start: '2026-10-01',
  end: '2026-10-03',
  quantity: 1,
  adults: 2,
  children: 0,
};

describe('AvailabilityStore', () => {
  let store: AvailabilityStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(AvailabilityStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('loadReferenceData() populates properties and room types', async () => {
    const promise = store.loadReferenceData();

    httpMock
      .expectOne(`${environment.apiBaseUrl}/properties/`)
      .flush([{ id: 1, code: 'T1', name: 'Test Hotel', status: 'active', currency: 'NGN', timezone: 'UTC' }]);
    httpMock
      .expectOne(`${environment.apiBaseUrl}/room-types/`)
      .flush([{ id: 1, code: 'STD', name: 'Standard', status: 'active', max_occupancy: 2, attributes: {} }]);

    await promise;
    expect(store.properties().length).toBe(1);
    expect(store.roomTypes().length).toBe(1);
  });

  it('search() sets loading, then replaces result with the server response', async () => {
    const promise = store.search(PARAMS);
    expect(store.loading()).toBe(true);

    const req = httpMock.expectOne(
      (r) => r.url === `${environment.apiBaseUrl}/availability/` && r.params.get('property_id') === '1',
    );
    req.flush({
      property_id: 1, room_type_id: 1, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: true, remaining_by_date: { '2026-10-01': 5, '2026-10-02': 5 },
      price: { nightly: [], stay_adjustments: [], subtotal_minor_units: 20000, total_minor_units: 20000, currency: 'NGN', floor_minor_units: null, ceiling_minor_units: null },
      price_error: null,
    });

    await promise;
    expect(store.loading()).toBe(false);
    expect(store.result()?.sellable).toBe(true);
    expect(store.error()).toBeNull();
  });

  it('a second search REPLACES the previous result rather than merging', async () => {
    const first = store.search(PARAMS);
    httpMock.expectOne((r) => r.url.includes('/availability/') && r.params.get('start') === '2026-10-01').flush({
      property_id: 1, room_type_id: 1, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: true, remaining_by_date: { '2026-10-01': 5 }, price: null, price_error: null,
    });
    await first;

    const second = store.search({ ...PARAMS, start: '2026-11-01', end: '2026-11-03' });
    httpMock.expectOne((r) => r.params.get('start') === '2026-11-01').flush({
      property_id: 1, room_type_id: 1, start: '2026-11-01', end: '2026-11-03', quantity: 1,
      sellable: false, remaining_by_date: { '2026-11-01': 0 }, price: null, price_error: null,
    });
    await second;

    expect(store.result()?.start).toBe('2026-11-01');
    expect(store.result()?.sellable).toBe(false);
  });

  it('empty result: sellable false with no price is rendered as-is, not guessed', async () => {
    const promise = store.search(PARAMS);
    httpMock.expectOne((r) => r.url.includes('/availability/')).flush({
      property_id: 1, room_type_id: 1, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: false, remaining_by_date: {}, price: null, price_error: 'no rate plan',
    });
    await promise;

    expect(store.result()?.sellable).toBe(false);
    expect(store.result()?.price).toBeNull();
    expect(store.result()?.price_error).toBe('no rate plan');
  });

  it('search() failure sets error and clears any previous result', async () => {
    const promise = store.search(PARAMS);
    httpMock
      .expectOne((r) => r.url.includes('/availability/'))
      .flush({ detail: 'property not found.' }, { status: 404, statusText: 'Not Found' });

    await promise;
    expect(store.result()).toBeNull();
    expect(store.error()?.message).toBe('property not found.');
  });

  it('refresh() re-issues the last search verbatim', async () => {
    const first = store.search(PARAMS);
    httpMock.expectOne((r) => r.url.includes('/availability/')).flush({
      property_id: 1, room_type_id: 1, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: true, remaining_by_date: {}, price: null, price_error: null,
    });
    await first;

    const refreshPromise = store.refresh();
    const req = httpMock.expectOne((r) => r.url.includes('/availability/'));
    expect(req.request.params.get('start')).toBe('2026-10-01');
    req.flush({
      property_id: 1, room_type_id: 1, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: false, remaining_by_date: {}, price: null, price_error: null,
    });
    await refreshPromise;

    expect(store.result()?.sellable).toBe(false);
  });
});
