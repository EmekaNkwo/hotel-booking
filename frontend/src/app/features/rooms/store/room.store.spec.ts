import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { RoomStore } from './room.store';
import { Room } from '../models/room.model';
import { environment } from '../../../../environments/environment';

const ROOM: Room = {
  id: 1, code: '101', property_id: 1,
  room_type: { id: 1, code: 'STD', name: 'Standard', status: 'active', max_occupancy: 2, attributes: {} },
  operational_state: 'vacant_clean', current_booking_line_id: null,
};

describe('RoomStore', () => {
  let store: RoomStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(RoomStore);
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

  it('loadList() with no filters hits the plain endpoint (only ?page=) and replaces the list', async () => {
    const promise = store.loadList();
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/rooms/?page=1`);
    expect(req.request.params.keys()).toEqual(['page']);
    req.flush({ count: 1, next: null, previous: null, results: [ROOM] });
    await promise;
    expect(store.list().length).toBe(1);
    expect(store.list()[0].code).toBe('101');
  });

  it('loadList() with filters sends them as query params (server-side filtering)', async () => {
    const promise = store.loadList({ property_id: 1, operational_state: 'vacant_clean' });
    const req = httpMock.expectOne(
      (r) => r.url === `${environment.apiBaseUrl}/rooms/` &&
        r.params.get('property_id') === '1' &&
        r.params.get('operational_state') === 'vacant_clean',
    );
    req.flush({ count: 1, next: null, previous: null, results: [ROOM] });
    await promise;
    expect(store.list().length).toBe(1);
  });

  it('a second loadList() REPLACES the previous list rather than merging', async () => {
    const first = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/rooms/?page=1`)
      .flush({ count: 1, next: null, previous: null, results: [ROOM] });
    await first;

    const second = store.loadList({ operational_state: 'out_of_service' });
    httpMock
      .expectOne((r) => r.params.get('operational_state') === 'out_of_service')
      .flush({ count: 0, next: null, previous: null, results: [] });
    await second;

    expect(store.list()).toEqual([]);
  });

  it('loadList() failure clears the list and sets listError', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/rooms/?page=1`)
      .flush({ detail: 'nope' }, { status: 403, statusText: 'Forbidden' });
    await promise;
    expect(store.list()).toEqual([]);
    expect(store.listError()?.message).toBe('nope');
  });

  it('loadOne() populates current from the authoritative detail response', async () => {
    const promise = store.loadOne(1);
    httpMock.expectOne(`${environment.apiBaseUrl}/rooms/1/`).flush(ROOM);
    await promise;
    expect(store.current()?.code).toBe('101');
  });

  it('loadOne() failure clears current and sets detailError', async () => {
    const promise = store.loadOne(999);
    httpMock
      .expectOne(`${environment.apiBaseUrl}/rooms/999/`)
      .flush({ detail: 'room not found.' }, { status: 404, statusText: 'Not Found' });
    await promise;
    expect(store.current()).toBeNull();
    expect(store.detailError()?.message).toBe('room not found.');
  });

  describe('R0.10: out-of-order responses', () => {
    const ROOM_2 = { ...ROOM, id: 2, code: '102' };

    it('loadOne(101) then loadOne(102): a late-resolving response for 101 must not overwrite 102', async () => {
      const first = store.loadOne(1);
      const firstReq = httpMock.expectOne(`${environment.apiBaseUrl}/rooms/1/`);

      const second = store.loadOne(2);
      const secondReq = httpMock.expectOne(`${environment.apiBaseUrl}/rooms/2/`);

      secondReq.flush(ROOM_2);
      await second;
      expect(store.current()?.id).toBe(2);

      firstReq.flush(ROOM);
      await first;
      expect(store.current()?.id).toBe(2); // stale response ignored
    });

    it('two loadList() calls (e.g. rapid filter changes): only the latest filter\'s results apply', async () => {
      const first = store.loadList({ operational_state: 'vacant_clean' });
      const firstReq = httpMock.expectOne(
        (r) => r.params.get('operational_state') === 'vacant_clean',
      );

      const second = store.loadList({ operational_state: 'out_of_service' });
      const secondReq = httpMock.expectOne(
        (r) => r.params.get('operational_state') === 'out_of_service',
      );

      // The SECOND (newer) filter's request resolves first...
      secondReq.flush({ count: 1, next: null, previous: null, results: [ROOM_2] });
      await second;
      expect(store.list()).toEqual([ROOM_2]);

      // ...then the stale first request finally resolves — ignored.
      firstReq.flush({ count: 1, next: null, previous: null, results: [ROOM] });
      await first;
      expect(store.list()).toEqual([ROOM_2]);
    });
  });

  describe('R1.1: pagination', () => {
    it('nextPage() preserves the active filter and replaces the list with page 2', async () => {
      const load1 = store.loadList({ operational_state: 'vacant_clean' });
      httpMock
        .expectOne((r) => r.params.get('page') === '1' && r.params.get('operational_state') === 'vacant_clean')
        .flush({ count: 30, next: 'http://x/rooms/?page=2', previous: null, results: [ROOM] });
      await load1;
      expect(store.hasNextPage()).toBe(true);

      const load2 = store.nextPage();
      httpMock
        .expectOne((r) => r.params.get('page') === '2' && r.params.get('operational_state') === 'vacant_clean')
        .flush({ count: 30, next: null, previous: 'http://x/rooms/?page=1', results: [{ ...ROOM, id: 2, code: '102' }] });
      await load2;
      expect(store.currentPage()).toBe(2);
      expect(store.list()).toEqual([{ ...ROOM, id: 2, code: '102' }]);
      expect(store.count()).toBe(30);
    });

    it('previousPage() is a no-op when the server reports no previous page', async () => {
      const load1 = store.loadList();
      httpMock
        .expectOne(`${environment.apiBaseUrl}/rooms/?page=1`)
        .flush({ count: 1, next: null, previous: null, results: [ROOM] });
      await load1;
      await store.previousPage();
      httpMock.expectNone((r) => r.params.get('page') === '0');
    });
  });
});
