import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { DashboardPage } from './dashboard-page';
import { DashboardStore } from '../store/dashboard.store';
import { NotificationJob } from '../../notifications/models/notification-job.model';

const NOTIFICATION: NotificationJob = {
  id: 9, notification_type: 'booking_confirmed', channel: 'email', status: 'dead_lettered', retry_count: 5,
  last_error: 'SMTP timeout', recipient_guest_id: 1, context: {}, created_at: '2026-10-01T00:00:00Z',
};

describe('DashboardPage', () => {
  let fixture: ComponentFixture<DashboardPage>;
  let store: DashboardStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [DashboardPage, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(DashboardPage);
    store = TestBed.inject(DashboardStore);
    vi.spyOn(store, 'loadAll').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads all panels on init', () => {
    expect(store.loadAll).toHaveBeenCalled();
  });

  it('refresh() re-issues loadAll()', () => {
    (store.loadAll as ReturnType<typeof vi.fn>).mockClear();
    fixture.nativeElement.querySelector('button').click();
    expect(store.loadAll).toHaveBeenCalled();
  });

  it('shows a per-panel loading state without blanking the rest of the page', () => {
    store.bookings.set({ data: null, loading: true, error: null });
    store.rooms.set({ data: [], loading: false, error: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Rooms');
    expect(fixture.nativeElement.textContent).toContain('Loading');
  });

  it('shows a localized error on one panel while others still render', () => {
    store.bookings.set({ data: null, loading: false, error: { status: 500, message: 'booking service down.', raw: null } });
    store.rooms.set({
      data: [{
        id: 1, code: '101', property_id: 1,
        room_type: { id: 1, code: 'STD', name: 'Standard', status: 'active', max_occupancy: 3, attributes: {} },
        operational_state: 'vacant_clean', current_booking_line_id: null,
      }],
      loading: false,
      error: null,
    });
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('booking service down.');
    expect(text).toContain('Vacant clean');
  });

  it('links to a real notification detail page by id', () => {
    store.problemNotifications.set({ data: [NOTIFICATION], loading: false, error: null });
    fixture.detectChanges();
    const link = fixture.nativeElement.querySelector('a[href="/notifications/9"]');
    expect(link).toBeTruthy();
  });

  it('links to real bookings/rooms/housekeeping/reservations/notifications list pages', () => {
    store.rooms.set({ data: [], loading: false, error: null });
    store.housekeepingTasks.set({ data: [], loading: false, error: null });
    store.reservations.set({ data: [], loading: false, error: null });
    store.bookings.set({ data: [], loading: false, error: null });
    store.problemNotifications.set({ data: [], loading: false, error: null });
    fixture.detectChanges();
    const anchors: HTMLAnchorElement[] = Array.from(fixture.nativeElement.querySelectorAll('a'));
    const hrefs = anchors.map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('/rooms');
    expect(hrefs).toContain('/housekeeping');
    expect(hrefs).toContain('/reservations');
    expect(hrefs).toContain('/notifications');
  });
});
