import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { NotificationListPage } from './notification-list-page';
import { NotificationStore } from '../store/notification.store';
import { NotificationJob } from '../models/notification-job.model';

const JOB: NotificationJob = {
  id: 1,
  notification_type: 'booking_confirmed',
  channel: 'email',
  status: 'delivered',
  retry_count: 0,
  last_error: '',
  recipient_guest_id: 7,
  context: {},
  created_at: '2026-10-03T00:00:00Z',
};

describe('NotificationListPage', () => {
  let fixture: ComponentFixture<NotificationListPage>;
  let component: NotificationListPage;
  let store: NotificationStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [NotificationListPage, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(NotificationListPage);
    component = fixture.componentInstance;
    store = TestBed.inject(NotificationStore);
    vi.spyOn(store, 'loadList').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the unfiltered job list on init', () => {
    expect(store.loadList).toHaveBeenCalledWith();
  });

  it('shows a loading indicator while in flight', () => {
    store.listLoading.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Loading');
  });

  it('shows an empty state when there are no jobs', () => {
    store.jobs.set([]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-empty-state')).toBeTruthy();
  });

  it('renders a row per job, including its status badge, and no invented action buttons', () => {
    store.jobs.set([JOB]);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('booking_confirmed');
    expect(fixture.nativeElement.querySelector('app-notification-status-badge')).toBeTruthy();
    expect(text).not.toContain('Retry');
    expect(text).not.toContain('Requeue');
  });

  it('renders the backend error message on a list failure', () => {
    store.listError.set({ status: 403, message: 'not allowed.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('not allowed.');
  });

  it('applyFilters() re-issues loadList with the current status filter (server-side filtering)', () => {
    component['filterForm'].setValue({ status: 'failed' });

    component.applyFilters();

    expect(store.loadList).toHaveBeenCalledWith({ status: 'failed' });
  });

  it('clearFilters() resets the form and reloads with no filters', () => {
    component['filterForm'].setValue({ status: 'dead_lettered' });

    component.clearFilters();

    expect(component['filterForm'].getRawValue()).toEqual({ status: null });
    expect(store.loadList).toHaveBeenLastCalledWith({});
  });
});
