import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ReservationNewPage } from './reservation-new-page';
import { ReservationStore } from '../store/reservation.store';
import { Reservation } from '../models/reservation.model';
import { GuestProfile } from '../../guests/models/guest.model';

const GUEST: GuestProfile = {
  id: 1, primary_email: 'guest@example.com', primary_phone: null,
  name: { given_name: 'Jane', family_name: 'Doe', display_name: 'Jane Doe' },
  language: '', status: 'active', created_at: '2026-01-01T00:00:00Z',
};

const SELECTION = {
  property_id: 1, room_type_id: 2, start: '2026-10-01', end: '2026-10-03',
  quantity: 1, adults: 2, children: 0,
};

describe('ReservationNewPage', () => {
  let fixture: ComponentFixture<ReservationNewPage>;
  let component: ReservationNewPage;
  let store: ReservationStore;
  let router: Router;

  function setup(state: unknown) {
    TestBed.configureTestingModule({
      imports: [ReservationNewPage, NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'reservations/:id', children: [] }]),
      ],
    });
    window.history.replaceState(state, '');
    fixture = TestBed.createComponent(ReservationNewPage);
    component = fixture.componentInstance;
    store = TestBed.inject(ReservationStore);
    router = TestBed.inject(Router);
    fixture.detectChanges();
  }

  afterEach(() => {
    window.history.replaceState({}, '');
  });

  it('shows a prompt to go back to availability search when no selection was carried over', () => {
    setup(null);
    expect(fixture.nativeElement.textContent).toContain('No stay selected');
  });

  it('renders the stay summary and guest search when a selection was carried over', () => {
    setup(SELECTION);
    expect(fixture.nativeElement.textContent).toContain('2026-10-01');
    expect(fixture.nativeElement.querySelector('app-guest-search')).toBeTruthy();
  });

  it('onGuestSelected() records the selected guest', () => {
    setup(SELECTION);
    component.onGuestSelected(GUEST);
    expect(component['selectedGuest']()).toEqual(GUEST);
  });

  it('submit() does nothing without a selected guest', async () => {
    setup(SELECTION);
    const createSpy = vi.spyOn(store, 'create');
    await component.submit();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it('submit() creates the reservation with the carried-over stay and selected guest, then navigates', async () => {
    setup(SELECTION);
    component.onGuestSelected(GUEST);
    const created: Reservation = {
      id: 42, reservation_ref: 'REF1', status: 'held', channel: 'direct', hold_expiry_at: null,
      price_snapshot: {}, policy_snapshot: {}, guest_profile_id: 1, property_id: 1, lines: [], created_at: '2026-09-01T00:00:00Z',
    };
    const createSpy = vi.spyOn(store, 'create').mockResolvedValue(created);
    const navigateSpy = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    await component.submit();

    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        property_id: 1,
        guest_email: 'guest@example.com',
        lines: [{ room_type_id: 2, arrival_date: '2026-10-01', departure_date: '2026-10-03', adults: 2, children: 0, quantity: 1 }],
      }),
    );
    expect(navigateSpy).toHaveBeenCalledWith(['/reservations', 42]);
  });

  it('submit() does not navigate on failure, and reuses the same idempotency key on retry', async () => {
    setup(SELECTION);
    component.onGuestSelected(GUEST);
    const createSpy = vi.spyOn(store, 'create').mockResolvedValue(null);
    const navigateSpy = vi.spyOn(router, 'navigate');

    await component.submit();
    await component.submit();

    expect(navigateSpy).not.toHaveBeenCalled();
    const firstKey = createSpy.mock.calls[0][0].idempotency_key;
    const secondKey = createSpy.mock.calls[1][0].idempotency_key;
    expect(firstKey).toBeTruthy();
    expect(firstKey).toBe(secondKey);
  });
});
