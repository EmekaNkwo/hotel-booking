import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { AllocationStore } from './allocation.store';
import { AllocationRecord } from '../models/allocation-record.model';
import { environment } from '../../../../environments/environment';

const RECORD: AllocationRecord = {
  id: 1, booking_line_id: 5, room_id: 101, override: false, override_reason: '',
  criteria: { room_type_id: 1 }, scores: { '101': { score: 1 } }, reason: 'only eligible room',
  created_at: '2026-09-01T00:00:00Z',
};

describe('AllocationStore', () => {
  let store: AllocationStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(AllocationStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('isLoading()/errorFor() default to false/null for an untouched line', () => {
    expect(store.isLoading(999)).toBe(false);
    expect(store.errorFor(999)).toBeNull();
  });

  it('allocate() success stores the record keyed by booking_line_id (never assumed locally)', async () => {
    const promise = store.allocate({ booking_line_id: 5, idempotency_key: 'k1' });
    expect(store.isLoading(5)).toBe(true);

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/allocation/allocate/`);
    expect(req.request.body).toEqual({ booking_line_id: 5, idempotency_key: 'k1' });
    req.flush(RECORD, { status: 201, statusText: 'Created' });

    const result = await promise;
    expect(result?.room_id).toBe(101);
    expect(store.recordsByLine()[5]?.room_id).toBe(101);
    expect(store.isLoading(5)).toBe(false);
  });

  it('allocate() 409 does not store a record and surfaces the backend message for that line only', async () => {
    const promise = store.allocate({ booking_line_id: 5, idempotency_key: 'k1' });

    httpMock
      .expectOne(`${environment.apiBaseUrl}/allocation/allocate/`)
      .flush({ detail: 'no eligible room.' }, { status: 409, statusText: 'Conflict' });

    const result = await promise;
    expect(result).toBeNull();
    expect(store.recordsByLine()[5]).toBeUndefined();
    expect(store.errorFor(5)?.status).toBe(409);
    expect(store.errorFor(5)?.message).toBe('no eligible room.');
    expect(store.errorFor(6)).toBeNull(); // a different line is unaffected
  });

  it('a fresh allocate() attempt clears the previous error for that line', async () => {
    const first = store.allocate({ booking_line_id: 5 });
    httpMock
      .expectOne(`${environment.apiBaseUrl}/allocation/allocate/`)
      .flush({ detail: 'conflict' }, { status: 409, statusText: 'Conflict' });
    await first;
    expect(store.errorFor(5)).not.toBeNull();

    const second = store.allocate({ booking_line_id: 5, idempotency_key: 'k2' });
    expect(store.errorFor(5)).toBeNull();
    httpMock.expectOne(`${environment.apiBaseUrl}/allocation/allocate/`).flush(RECORD, { status: 201, statusText: 'Created' });
    await second;
  });
});
