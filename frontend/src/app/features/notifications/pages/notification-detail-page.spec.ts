import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';

import { NotificationDetailPage } from './notification-detail-page';
import { NotificationStore } from '../store/notification.store';
import { NotificationJob } from '../models/notification-job.model';

const DELIVERED: NotificationJob = {
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

const DEAD_LETTERED: NotificationJob = {
  ...DELIVERED,
  id: 2,
  status: 'dead_lettered',
  retry_count: 5,
  last_error: 'SMTP timeout after 5 attempts.',
};

function setup(id = '1') {
  TestBed.configureTestingModule({
    imports: [NotificationDetailPage],
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ id }) } },
      },
    ],
  });
  const fixture = TestBed.createComponent(NotificationDetailPage);
  const store = TestBed.inject(NotificationStore);
  return { fixture, store };
}

describe('NotificationDetailPage', () => {
  it('loads the job by route id on init', () => {
    const { fixture, store } = setup('42');
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    fixture.detectChanges();
    expect(store.loadOne).toHaveBeenCalledWith(42);
  });

  it('shows a loading indicator before the job arrives', () => {
    const { fixture, store } = setup();
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    store.detailLoading.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Loading');
  });

  it('renders job facts and status badge, with no invented retry/delete/edit actions', () => {
    const { fixture, store } = setup();
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    store.current.set(DELIVERED);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('booking_confirmed');
    expect(text).toContain('email');
    expect(fixture.nativeElement.querySelector('app-notification-status-badge')).toBeTruthy();
    expect(text).not.toContain('Retry job');
    expect(text).not.toContain('Requeue');
    expect(fixture.nativeElement.querySelector('button')).toBeFalsy();
  });

  it('shows a linked recipient guest when recipient_guest_id is present', () => {
    const { fixture, store } = setup();
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    store.current.set(DELIVERED);
    fixture.detectChanges();
    const link = fixture.nativeElement.querySelector('a[href="/guests/7"]');
    expect(link).toBeTruthy();
  });

  it('shows the failure box with last_error for a dead-lettered job', () => {
    const { fixture, store } = setup();
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    store.current.set(DEAD_LETTERED);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Dead-lettered');
    expect(text).toContain('SMTP timeout after 5 attempts.');
    expect(fixture.nativeElement.querySelector('.failure-box.dead-lettered')).toBeTruthy();
  });

  it('does not show a failure box for a delivered job', () => {
    const { fixture, store } = setup();
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    store.current.set(DELIVERED);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.failure-box')).toBeFalsy();
  });

  it('renders the backend error message on a detail load failure', () => {
    const { fixture, store } = setup();
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    store.detailError.set({ status: 404, message: 'not found.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('not found.');
  });
});
