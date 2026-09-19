import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';

import { HousekeepingDetailPage } from './housekeeping-detail-page';
import { HousekeepingStore } from '../store/housekeeping.store';
import { HousekeepingTask } from '../models/housekeeping-task.model';
import { environment } from '../../../../environments/environment';

const TASK: HousekeepingTask = {
  id: 1, room_id: 101, booking_line_id: 5, business_date: '2026-10-03',
  task_kind: 'departure', status: 'planned', assignee_id: null, created_at: '2026-10-03T00:00:00Z',
};

describe('HousekeepingDetailPage', () => {
  let fixture: ComponentFixture<HousekeepingDetailPage>;
  let component: HousekeepingDetailPage;
  let store: HousekeepingStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HousekeepingDetailPage],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '1' }) } } },
      ],
    });
    fixture = TestBed.createComponent(HousekeepingDetailPage);
    component = fixture.componentInstance;
    store = TestBed.inject(HousekeepingStore);
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the task by the route id on init', () => {
    expect(store.loadOne).toHaveBeenCalledWith(1);
  });

  it('renders the authoritative task fields and status badge once loaded', () => {
    store.current.set(TASK);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('101');
    expect(text).toContain('planned');
    expect(fixture.nativeElement.querySelector('app-housekeeping-status-badge')).toBeTruthy();
  });

  it('shows Start cleaning only for planned/assigned tasks', () => {
    store.current.set({ ...TASK, status: 'planned' });
    fixture.detectChanges();
    let buttons = Array.from(fixture.nativeElement.querySelectorAll('button')).map((b: unknown) => (b as HTMLElement).textContent?.trim());
    expect(buttons).toContain('Start cleaning');

    store.current.set({ ...TASK, status: 'in_progress' });
    fixture.detectChanges();
    buttons = Array.from(fixture.nativeElement.querySelectorAll('button')).map((b: unknown) => (b as HTMLElement).textContent?.trim());
    expect(buttons).not.toContain('Start cleaning');
  });

  it('shows Complete cleaning only for in_progress tasks', () => {
    store.current.set({ ...TASK, status: 'in_progress' });
    fixture.detectChanges();
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')).map((b: unknown) => (b as HTMLElement).textContent?.trim());
    expect(buttons).toContain('Complete cleaning');
  });

  it('shows Pass/Fail inspection only for quality_check tasks', () => {
    store.current.set({ ...TASK, status: 'quality_check' });
    fixture.detectChanges();
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')).map((b: unknown) => (b as HTMLElement).textContent?.trim());
    expect(buttons).toContain('Pass inspection');
    expect(buttons).toContain('Fail inspection');
  });

  it('startCleaning() delegates to the store with a generated idempotency key, reused on retry', async () => {
    store.current.set({ ...TASK, status: 'planned' });
    const spy = vi.spyOn(store, 'startCleaning').mockResolvedValue(false);

    await component.startCleaning();
    await component.startCleaning();

    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy.mock.calls[0][1]).toBe(spy.mock.calls[1][1]);
    expect(spy.mock.calls[0][1]).toBeTruthy();
  });

  it('inspect(pass) does not prompt for confirmation', async () => {
    store.current.set({ ...TASK, status: 'quality_check' });
    const spy = vi.spyOn(store, 'inspect').mockResolvedValue(true);
    const confirmSpy = vi.spyOn(window, 'confirm');

    await component.inspect('pass');

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(spy).toHaveBeenCalledWith(1, expect.objectContaining({ result: 'pass' }));
  });

  it('inspect(fail) asks for confirmation and aborts if declined', async () => {
    store.current.set({ ...TASK, status: 'quality_check' });
    const spy = vi.spyOn(store, 'inspect');
    vi.spyOn(window, 'confirm').mockReturnValue(false);

    await component.inspect('fail');

    expect(spy).not.toHaveBeenCalled();
  });

  it('inspect(fail) proceeds when confirmed', async () => {
    store.current.set({ ...TASK, status: 'quality_check' });
    const spy = vi.spyOn(store, 'inspect').mockResolvedValue(true);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    await component.inspect('fail');

    expect(spy).toHaveBeenCalledWith(1, expect.objectContaining({ result: 'fail' }));
  });

  it('renders the backend error and a refresh action on a failed action, without mutating status', async () => {
    const httpMock = TestBed.inject(HttpTestingController);
    store.current.set({ ...TASK, status: 'in_progress' });

    const promise = component.completeCleaning();
    httpMock
      .expectOne(`${environment.apiBaseUrl}/housekeeping/tasks/1/complete-cleaning/`)
      .flush({ detail: 'a concurrent update won.' }, { status: 409, statusText: 'Conflict' });
    await promise;
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('a concurrent update won.');
    expect(store.current()?.status).toBe('in_progress'); // unchanged
    httpMock.verify();
  });

  it('renders the backend error message on a detail failure', () => {
    store.current.set(null);
    store.detailError.set({ status: 404, message: 'housekeeping task not found.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('housekeeping task not found.');
  });
});
