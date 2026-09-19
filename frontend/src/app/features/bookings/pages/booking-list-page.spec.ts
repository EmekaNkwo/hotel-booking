import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { BookingListPage } from './booking-list-page';
import { BookingStore } from '../store/booking.store';
import { Booking } from '../models/booking.model';

const BOOKING: Booking = {
  id: 1, booking_ref: 'BR1', aggregate_status: 'confirmed', currency: 'NGN',
  total_minor_units: 20000, arrival_date: '2026-10-01', departure_date: '2026-10-03',
  guest_profile_id: 1, reservation_id: 5, guest_snapshot: {}, lines: [], created_at: '2026-09-01T00:00:00Z',
};

describe('BookingListPage', () => {
  let fixture: ComponentFixture<BookingListPage>;
  let store: BookingStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [BookingListPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(BookingListPage);
    store = TestBed.inject(BookingStore);
    vi.spyOn(store, 'loadList').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the booking list on init', () => {
    expect(store.loadList).toHaveBeenCalled();
  });

  it('shows an empty state when there are no bookings', () => {
    store.list.set([]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-empty-state')).toBeTruthy();
  });

  it('renders a row per booking from the store', () => {
    store.list.set([BOOKING]);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('BR1');
  });

  it('renders the backend error message on a list failure', () => {
    store.listError.set({ status: 403, message: 'not allowed.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('not allowed.');
  });
});
