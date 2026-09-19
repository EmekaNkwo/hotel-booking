import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { HousekeepingListPage } from './housekeeping-list-page';
import { HousekeepingStore } from '../store/housekeeping.store';
import { HousekeepingTask } from '../models/housekeeping-task.model';

const TASK: HousekeepingTask = {
  id: 1, room_id: 101, booking_line_id: 5, business_date: '2026-10-03',
  task_kind: 'departure', status: 'planned', assignee_id: null, created_at: '2026-10-03T00:00:00Z',
};

describe('HousekeepingListPage', () => {
  let fixture: ComponentFixture<HousekeepingListPage>;
  let component: HousekeepingListPage;
  let store: HousekeepingStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HousekeepingListPage, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(HousekeepingListPage);
    component = fixture.componentInstance;
    store = TestBed.inject(HousekeepingStore);
    vi.spyOn(store, 'loadList').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the unfiltered task list on init', () => {
    expect(store.loadList).toHaveBeenCalledWith();
  });

  it('shows a loading indicator while in flight', () => {
    store.listLoading.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Loading');
  });

  it('shows an empty state when there are no tasks', () => {
    store.tasks.set([]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-empty-state')).toBeTruthy();
  });

  it('renders a row per task, including its status badge', () => {
    store.tasks.set([TASK]);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('101');
    expect(fixture.nativeElement.querySelector('app-housekeeping-status-badge')).toBeTruthy();
  });

  it('renders the backend error message on a list failure', () => {
    store.listError.set({ status: 403, message: 'not allowed.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('not allowed.');
  });

  it('applyFilters() re-issues loadList with the current form values (server-side filtering)', () => {
    component['filterForm'].setValue({ status: 'in_progress', room_id: 101 });

    component.applyFilters();

    expect(store.loadList).toHaveBeenCalledWith({ status: 'in_progress', room_id: 101 });
  });

  it('clearFilters() resets the form and reloads with no filters', () => {
    component['filterForm'].setValue({ status: 'defect', room_id: 5 });

    component.clearFilters();

    expect(component['filterForm'].getRawValue()).toEqual({ status: null, room_id: null });
    expect(store.loadList).toHaveBeenLastCalledWith({});
  });
});
