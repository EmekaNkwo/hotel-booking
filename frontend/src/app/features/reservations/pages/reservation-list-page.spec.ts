import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { ReservationListPage } from './reservation-list-page';
import { ReservationStore } from '../store/reservation.store';
import { Reservation } from '../models/reservation.model';

const RESERVATION: Reservation = {
  id: 1, reservation_ref: 'REF1', status: 'held', channel: 'direct', hold_expiry_at: null,
  price_snapshot: {}, policy_snapshot: {}, guest_profile_id: 1, property_id: 1, lines: [], created_at: '2026-09-01T00:00:00Z',
};

describe('ReservationListPage', () => {
  let fixture: ComponentFixture<ReservationListPage>;
  let store: ReservationStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ReservationListPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(ReservationListPage);
    store = TestBed.inject(ReservationStore);
    vi.spyOn(store, 'loadList').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the reservation list on init', () => {
    expect(store.loadList).toHaveBeenCalled();
  });

  it('shows an empty state when there are no reservations', () => {
    store.list.set([]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-empty-state')).toBeTruthy();
  });

  it('renders a row per reservation from the store', () => {
    store.list.set([RESERVATION]);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('REF1');
  });

  it('renders the backend error message on a list failure', () => {
    store.listError.set({ status: 403, message: 'not allowed.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('not allowed.');
  });
});
