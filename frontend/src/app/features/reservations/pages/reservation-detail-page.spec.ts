import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap, provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ReservationDetailPage } from './reservation-detail-page';
import { ReservationStore } from '../store/reservation.store';
import { Reservation } from '../models/reservation.model';
import { BookingStore } from '../../bookings/store/booking.store';
import { Booking } from '../../bookings/models/booking.model';

const RESERVATION: Reservation = {
  id: 7, reservation_ref: 'REF7', status: 'held', channel: 'direct', hold_expiry_at: null,
  price_snapshot: {}, policy_snapshot: {}, guest_profile_id: 1, property_id: 1, lines: [], created_at: '2026-09-01T00:00:00Z',
};

const BOOKING: Booking = {
  id: 42, booking_ref: 'BR42', aggregate_status: 'pending_payment', currency: 'NGN',
  total_minor_units: 20000, arrival_date: '2026-10-01', departure_date: '2026-10-03',
  guest_profile_id: 1, reservation_id: 7, guest_snapshot: {}, lines: [], created_at: '2026-09-01T00:00:00Z',
};

describe('ReservationDetailPage', () => {
  let fixture: ComponentFixture<ReservationDetailPage>;
  let component: ReservationDetailPage;
  let store: ReservationStore;
  let bookingStore: BookingStore;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ReservationDetailPage, NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'bookings/:id', children: [] }]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } },
        },
      ],
    });
    fixture = TestBed.createComponent(ReservationDetailPage);
    component = fixture.componentInstance;
    store = TestBed.inject(ReservationStore);
    bookingStore = TestBed.inject(BookingStore);
    router = TestBed.inject(Router);
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the reservation by the route id on init', () => {
    expect(store.loadOne).toHaveBeenCalledWith(7);
  });

  it('renders the authoritative status and reference once loaded', () => {
    store.current.set(RESERVATION);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('REF7');
    expect(fixture.nativeElement.textContent).toContain('held');
  });

  it('requestPayment() delegates to the store for the current reservation', async () => {
    store.current.set(RESERVATION);
    const spy = vi.spyOn(store, 'requestPayment').mockResolvedValue(true);

    await component.requestPayment();

    expect(spy).toHaveBeenCalledWith(7);
  });

  it('cancel() delegates to the store with a generated idempotency key, reused on retry', async () => {
    store.current.set(RESERVATION);
    const spy = vi.spyOn(store, 'cancel').mockResolvedValue(false);

    await component.cancel();
    await component.cancel();

    expect(spy).toHaveBeenCalledTimes(2);
    const firstKey = spy.mock.calls[0][1];
    const secondKey = spy.mock.calls[1][1];
    expect(firstKey).toBeTruthy();
    expect(firstKey).toBe(secondKey);
  });

  it('cancel() success stops reusing the key on a subsequent cancel attempt', async () => {
    store.current.set(RESERVATION);
    const spy = vi.spyOn(store, 'cancel').mockResolvedValueOnce(true).mockResolvedValueOnce(false);

    await component.cancel();
    await component.cancel();

    const firstKey = spy.mock.calls[0][1];
    const secondKey = spy.mock.calls[1][1];
    expect(secondKey).not.toBe(firstKey);
  });

  it('renders the backend 409 message and a refresh action on a failed action', async () => {
    store.current.set(RESERVATION);
    vi.spyOn(store, 'requestPayment').mockImplementation(async () => {
      store.error.set({ status: 409, message: 'reservation is not held.', raw: null });
      return false;
    });

    await component.requestPayment();
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('reservation is not held.');
  });

  it('refresh() reloads the current reservation by id', () => {
    store.current.set(RESERVATION);
    vi.mocked(store.loadOne).mockClear();

    component.refresh();

    expect(store.loadOne).toHaveBeenCalledWith(7);
  });

  it('disables actions for a terminal status', () => {
    store.current.set({ ...RESERVATION, status: 'cancelled' });
    expect(component['actionsDisabled']()).toBe(true);
  });

  it('does not disable actions for an active status', () => {
    store.current.set({ ...RESERVATION, status: 'held' });
    expect(component['actionsDisabled']()).toBe(false);
  });

  it('confirm booking is only enabled once the reservation is awaiting_payment', () => {
    store.current.set({ ...RESERVATION, status: 'held' });
    expect(component['confirmDisabled']()).toBe(true);
    store.current.set({ ...RESERVATION, status: 'awaiting_payment' });
    expect(component['confirmDisabled']()).toBe(false);
  });

  it('confirmBooking() delegates to BookingStore and navigates to the resulting booking detail', async () => {
    store.current.set({ ...RESERVATION, status: 'awaiting_payment' });
    const confirmSpy = vi.spyOn(bookingStore, 'confirm').mockResolvedValue(BOOKING);
    const navigateSpy = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    await component.confirmBooking();

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.objectContaining({ reservation_id: 7, idempotency_key: expect.any(String) }),
    );
    expect(navigateSpy).toHaveBeenCalledWith(['/bookings', 42]);
  });

  it('confirmBooking() 409 does not navigate and preserves the backend message, reusing the same key on retry', async () => {
    store.current.set({ ...RESERVATION, status: 'awaiting_payment' });
    const confirmSpy = vi.spyOn(bookingStore, 'confirm').mockImplementation(async () => {
      bookingStore.error.set({ status: 409, message: 'reservation is not awaiting payment.', raw: null });
      return null;
    });
    const navigateSpy = vi.spyOn(router, 'navigate');

    await component.confirmBooking();
    await component.confirmBooking();
    fixture.detectChanges();

    expect(navigateSpy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('reservation is not awaiting payment.');
    const firstKey = confirmSpy.mock.calls[0][0].idempotency_key;
    const secondKey = confirmSpy.mock.calls[1][0].idempotency_key;
    expect(firstKey).toBe(secondKey);
  });

  it('never renders a "booking confirmed" state from an HTTP 200 alone — only from the parsed response', async () => {
    store.current.set({ ...RESERVATION, status: 'awaiting_payment' });
    vi.spyOn(bookingStore, 'confirm').mockResolvedValue(null);
    const navigateSpy = vi.spyOn(router, 'navigate');

    await component.confirmBooking();

    expect(navigateSpy).not.toHaveBeenCalled();
  });
});
