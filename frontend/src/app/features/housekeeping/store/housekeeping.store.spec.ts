import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { HousekeepingStore } from './housekeeping.store';
import { HousekeepingTask } from '../models/housekeeping-task.model';
import { environment } from '../../../../environments/environment';

const TASK: HousekeepingTask = {
  id: 1, room_id: 101, booking_line_id: 5, business_date: '2026-10-03',
  task_kind: 'departure', status: 'planned', assignee_id: null, created_at: '2026-10-03T00:00:00Z',
};

describe('HousekeepingStore', () => {
  let store: HousekeepingStore;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(HousekeepingStore);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('isCheckoutLoading()/checkoutErrorFor() default to false/null', () => {
    expect(store.isCheckoutLoading(999)).toBe(false);
    expect(store.checkoutErrorFor(999)).toBeNull();
  });

  it('isActionLoading()/actionErrorFor() default to false/null', () => {
    expect(store.isActionLoading(999)).toBe(false);
    expect(store.actionErrorFor(999)).toBeNull();
  });

  it('loadList() populates tasks from the server', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/?page=1`)
      .flush({ count: 1, next: null, previous: null, results: [TASK] });
    await promise;
    expect(store.tasks().length).toBe(1);
    expect(store.tasks()[0].room_id).toBe(101);
  });

  it('loadList() with filters sends them as query params', async () => {
    const promise = store.loadList({ status: 'in_progress', room_id: 101 });
    const req = httpMock.expectOne(
      (r) => r.url === `${environment.apiBaseUrl}/housekeeping/tasks/` &&
        r.params.get('status') === 'in_progress' && r.params.get('room_id') === '101',
    );
    req.flush({ count: 0, next: null, previous: null, results: [] });
    await promise;
    expect(store.tasks()).toEqual([]);
  });

  it('loadList() failure clears the list and sets listError', async () => {
    const promise = store.loadList();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/?page=1`)
      .flush({ detail: 'nope' }, { status: 403, statusText: 'Forbidden' });
    await promise;
    expect(store.tasks()).toEqual([]);
    expect(store.listError()?.message).toBe('nope');
  });

  it('loadOne() populates current from the authoritative detail response', async () => {
    const promise = store.loadOne(1);
    httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/`).flush(TASK);
    await promise;
    expect(store.current()?.status).toBe('planned');
  });

  it('checkout() success returns the created task without mutating any local list', async () => {
    const promise = store.checkout({ booking_line_id: 5, idempotency_key: 'k1' });
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/checkout/`);
    expect(req.request.body).toEqual({ booking_line_id: 5, idempotency_key: 'k1' });
    req.flush(TASK, { status: 201, statusText: 'Created' });

    const task = await promise;
    expect(task?.id).toBe(1);
    expect(store.tasks()).toEqual([]); // checkout never touches the task list directly
  });

  it('checkout() 409 sets the per-line error, keyed distinctly from other lines', async () => {
    const promise = store.checkout({ booking_line_id: 5, idempotency_key: 'k1' });
    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/checkout/`)
      .flush({ detail: 'line is not checked_in.' }, { status: 409, statusText: 'Conflict' });

    const task = await promise;
    expect(task).toBeNull();
    expect(store.checkoutErrorFor(5)?.message).toBe('line is not checked_in.');
    expect(store.checkoutErrorFor(6)).toBeNull();
  });

  it('startCleaning() success replaces current AND the matching list entry from the server response', async () => {
    store.tasks.set([TASK]);
    store.current.set(TASK);
    const promise = store.startCleaning(1, 'k1');

    const req = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/start-cleaning/`);
    expect(req.request.body).toEqual({ idempotency_key: 'k1' });
    req.flush({ ...TASK, status: 'in_progress' });

    const ok = await promise;
    expect(ok).toBe(true);
    expect(store.current()?.status).toBe('in_progress');
    expect(store.tasks()[0].status).toBe('in_progress');
  });

  it('startCleaning() 409 leaves current/tasks untouched and surfaces the backend message', async () => {
    store.tasks.set([TASK]);
    store.current.set(TASK);
    const promise = store.startCleaning(1);

    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/start-cleaning/`)
      .flush({ detail: 'a concurrent update won.' }, { status: 409, statusText: 'Conflict' });

    const ok = await promise;
    expect(ok).toBe(false);
    expect(store.current()?.status).toBe('planned'); // unchanged — no optimistic mutation
    expect(store.actionErrorFor(1)?.message).toBe('a concurrent update won.');
  });

  it('completeCleaning() success replaces state from the server', async () => {
    store.current.set({ ...TASK, status: 'in_progress' });
    const promise = store.completeCleaning(1);
    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/complete-cleaning/`)
      .flush({ ...TASK, status: 'quality_check' });
    const ok = await promise;
    expect(ok).toBe(true);
    expect(store.current()?.status).toBe('quality_check');
  });

  it('inspect() pass success replaces state from the server', async () => {
    store.current.set({ ...TASK, status: 'quality_check' });
    const promise = store.inspect(1, { result: 'pass', idempotency_key: 'k1' });
    const req = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/inspect/`);
    expect(req.request.body).toEqual({ result: 'pass', idempotency_key: 'k1' });
    req.flush({ ...TASK, status: 'verified' });
    const ok = await promise;
    expect(ok).toBe(true);
    expect(store.current()?.status).toBe('verified');
  });

  it('inspect() fail success replaces state from the server (no client-side OOS routing invented)', async () => {
    store.current.set({ ...TASK, status: 'quality_check' });
    const promise = store.inspect(1, { result: 'fail' });
    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/inspect/`)
      .flush({ ...TASK, status: 'defect' });
    const ok = await promise;
    expect(ok).toBe(true);
    expect(store.current()?.status).toBe('defect');
  });

  it('inspect() 409 does not mutate current and surfaces the backend message', async () => {
    store.current.set({ ...TASK, status: 'quality_check' });
    const promise = store.inspect(1, { result: 'pass' });
    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/inspect/`)
      .flush({ detail: 'task is not in quality_check.' }, { status: 409, statusText: 'Conflict' });
    const ok = await promise;
    expect(ok).toBe(false);
    expect(store.current()?.status).toBe('quality_check');
    expect(store.actionErrorFor(1)?.message).toBe('task is not in quality_check.');
  });

  describe('R1.1: pagination', () => {
    it('nextPage() replaces the task list with page 2 and preserves the active filter', async () => {
      const load1 = store.loadList({ status: 'planned' });
      httpMock
        .expectOne((r) => r.params.get('page') === '1' && r.params.get('status') === 'planned')
        .flush({ count: 30, next: 'http://x/housekeeping/tasks/?page=2', previous: null, results: [TASK] });
      await load1;
      expect(store.hasNextPage()).toBe(true);

      const load2 = store.nextPage();
      httpMock
        .expectOne((r) => r.params.get('page') === '2' && r.params.get('status') === 'planned')
        .flush({ count: 30, next: null, previous: 'http://x/housekeeping/tasks/?page=1', results: [{ ...TASK, id: 2 }] });
      await load2;
      expect(store.currentPage()).toBe(2);
      expect(store.tasks()).toEqual([{ ...TASK, id: 2 }]);
    });

    it('previousPage() is a no-op on page 1', async () => {
      const load1 = store.loadList();
      httpMock
        .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/?page=1`)
        .flush({ count: 1, next: null, previous: null, results: [TASK] });
      await load1;
      await store.previousPage();
      httpMock.expectNone((r) => r.params.get('page') === '0');
    });
  });

  describe('R1.2: out-of-order action state for the same task', () => {
    it('action A then action B for the same task, B resolves first, A resolves later: current/list/error/loading all end up consistent with B', async () => {
      store.tasks.set([TASK]);
      store.current.set(TASK);

      // A: start-cleaning
      const promiseA = store.startCleaning(1, 'key-a');
      const reqA = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/start-cleaning/`);

      // B: another action on the SAME task, issued after A but before A resolves
      const promiseB = store.completeCleaning(1);
      const reqB = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/complete-cleaning/`);

      expect(store.isActionLoading(1)).toBe(true);

      // B resolves FIRST (the later-issued command finishes before the earlier one).
      reqB.flush({ ...TASK, status: 'quality_check' });
      await promiseB;
      expect(store.current()?.status).toBe('quality_check');
      expect(store.tasks()[0].status).toBe('quality_check');
      expect(store.isActionLoading(1)).toBe(false);
      expect(store.actionErrorFor(1)).toBeNull();

      // A resolves LATE — it's stale relative to B and must not overwrite anything.
      reqA.flush({ ...TASK, status: 'in_progress' });
      await promiseA;
      expect(store.current()?.status).toBe('quality_check');
      expect(store.tasks()[0].status).toBe('quality_check');
      expect(store.isActionLoading(1)).toBe(false);
      expect(store.actionErrorFor(1)).toBeNull();
    });

    it('a stale action error does not clobber a newer action\'s success, and a stale success does not clear a newer action\'s error', async () => {
      store.tasks.set([TASK]);
      store.current.set(TASK);

      // A: start-cleaning (will fail late)
      const promiseA = store.startCleaning(1, 'key-a');
      const reqA = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/start-cleaning/`);

      // B: complete-cleaning, issued after A, succeeds first
      const promiseB = store.completeCleaning(1);
      const reqB = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/complete-cleaning/`);

      reqB.flush({ ...TASK, status: 'quality_check' });
      await promiseB;
      expect(store.tasks()[0].status).toBe('quality_check');

      // A's late failure must not retroactively mark the task as errored.
      reqA.flush({ detail: 'a concurrent update won.' }, { status: 409, statusText: 'Conflict' });
      await promiseA;
      expect(store.actionErrorFor(1)).toBeNull();
      expect(store.tasks()[0].status).toBe('quality_check');
    });

    it('actions on two different tasks never invalidate each other\'s state (per-task guard, not a single shared one)', async () => {
      const TASK_2 = { ...TASK, id: 2, room_id: 102 };
      store.tasks.set([TASK, TASK_2]);

      const promise1 = store.startCleaning(1);
      const req1 = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/start-cleaning/`);

      // A concurrent action on an UNRELATED task, issued after task 1's action.
      const promise2 = store.startCleaning(2);
      const req2 = httpMock.expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/2/start-cleaning/`);

      req2.flush({ ...TASK_2, status: 'in_progress' });
      await promise2;

      // Task 1's own action, resolving after task 2's, must still apply —
      // it is not stale with respect to ITS OWN task.
      req1.flush({ ...TASK, status: 'in_progress' });
      await promise1;

      expect(store.tasks().find((t) => t.id === 1)?.status).toBe('in_progress');
      expect(store.tasks().find((t) => t.id === 2)?.status).toBe('in_progress');
      expect(store.actionErrorFor(1)).toBeNull();
      expect(store.actionErrorFor(2)).toBeNull();
    });
  });
});
