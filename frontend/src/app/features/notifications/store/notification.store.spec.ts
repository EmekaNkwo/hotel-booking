import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { NotificationStore } from './notification.store';
import { NotificationJob } from '../models/notification-job.model';
import { environment } from '../../../../environments/environment';

const JOB: NotificationJob = {
  id: 1,
  notification_type: 'booking_confirmed',
  channel: 'email',
  status: 'delivered',
  retry_count: 0,
  last_error: '',
  recipient_guest_id: 7,
  context: { booking_id: 5 },
  created_at: '2026-10-03T00:00:00Z',
};

describe('NotificationStore', () => {
  let store: NotificationStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(NotificationStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('loadList() populates jobs and pagination state from the server', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/notifications/?page=1`)
      .flush({ count: 1, next: null, previous: null, results: [JOB] });
    await promise;
    expect(store.jobs().length).toBe(1);
    expect(store.jobs()[0].notification_type).toBe('booking_confirmed');
    expect(store.count()).toBe(1);
    expect(store.currentPage()).toBe(1);
  });

  it('loadList() with a status filter sends it as a query param', async () => {
    const promise = store.loadList({ status: 'failed' });
    const req = httpMock.expectOne(
      (r) => r.url === `${environment.apiBaseUrl}/notifications/` && r.params.get('status') === 'failed',
    );
    req.flush({ count: 0, next: null, previous: null, results: [] });
    await promise;
    expect(store.jobs()).toEqual([]);
  });

  it('loadList() failure clears jobs and sets listError, leaving detail state untouched', async () => {
    store.current.set(JOB);
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/notifications/?page=1`)
      .flush({ detail: 'nope' }, { status: 403, statusText: 'Forbidden' });
    await promise;
    expect(store.jobs()).toEqual([]);
    expect(store.listError()?.message).toBe('nope');
    expect(store.current()).toEqual(JOB);
  });

  it('loadOne() populates current from the authoritative detail response', async () => {
    const promise = store.loadOne(1);
    httpMock.expectOne(`${environment.apiBaseUrl}/notifications/1/`).flush(JOB);
    await promise;
    expect(store.current()?.status).toBe('delivered');
  });

  it('loadOne() failure sets detailError and clears current, leaving list state untouched', async () => {
    store.jobs.set([JOB]);
    const promise = store.loadOne(999);
    httpMock
      .expectOne(`${environment.apiBaseUrl}/notifications/999/`)
      .flush({ detail: 'not found.' }, { status: 404, statusText: 'Not Found' });
    await promise;
    expect(store.current()).toBeNull();
    expect(store.detailError()?.message).toBe('not found.');
    expect(store.jobs()).toEqual([JOB]);
  });

  describe('R1.1: pagination', () => {
    it('nextPage() replaces the job list with page 2, preserving the active filter', async () => {
      const load1 = store.loadList({ status: 'failed' });
      httpMock
        .expectOne((r) => r.params.get('page') === '1' && r.params.get('status') === 'failed')
        .flush({ count: 30, next: 'http://x/notifications/?page=2', previous: null, results: [JOB] });
      await load1;
      expect(store.hasNextPage()).toBe(true);

      const load2 = store.nextPage();
      httpMock
        .expectOne((r) => r.params.get('page') === '2' && r.params.get('status') === 'failed')
        .flush({ count: 30, next: null, previous: 'http://x/notifications/?page=1', results: [{ ...JOB, id: 2 }] });
      await load2;
      expect(store.currentPage()).toBe(2);
      expect(store.jobs()).toEqual([{ ...JOB, id: 2 }]);
      expect(store.hasNextPage()).toBe(false);
    });

    it('final page with an exact multiple of the page size correctly reports hasNextPage() as false', async () => {
      const promise = store.loadList();
      httpMock
        .expectOne(`${environment.apiBaseUrl}/notifications/?page=1`)
        .flush({ count: 25, next: null, previous: null, results: Array(25).fill(JOB) });
      await promise;
      expect(store.hasNextPage()).toBe(false);
      expect(store.count()).toBe(25);
    });
  });
});
