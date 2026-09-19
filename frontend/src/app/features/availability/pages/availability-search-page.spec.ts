import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { AvailabilitySearchPage } from './availability-search-page';
import { AvailabilityStore } from '../store/availability.store';

describe('AvailabilitySearchPage', () => {
  let fixture: ComponentFixture<AvailabilitySearchPage>;
  let component: AvailabilitySearchPage;
  let store: AvailabilityStore;
  let router: Router;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [AvailabilitySearchPage, NoopAnimationsModule],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'reservations/new', children: [] }]),
      ],
    });
    fixture = TestBed.createComponent(AvailabilitySearchPage);
    component = fixture.componentInstance;
    store = TestBed.inject(AvailabilityStore);
    router = TestBed.inject(Router);
    vi.spyOn(store, 'loadReferenceData').mockResolvedValue();
    fixture.detectChanges();
  });

  it('search is disabled until required fields are filled with a valid range', () => {
    expect(component['searchDisabled']()).toBe(true);

    component['form'].setValue({
      property_id: 1, room_type_id: 1, start: new Date('2026-10-01'), end: new Date('2026-10-03'),
      quantity: 1, adults: 1, children: 0,
    });

    expect(component['searchDisabled']()).toBe(false);
  });

  it('flags an invalid date range (checkout not after checkin)', () => {
    component['form'].setValue({
      property_id: 1, room_type_id: 1, start: new Date('2026-10-05'), end: new Date('2026-10-01'),
      quantity: 1, adults: 1, children: 0,
    });

    expect(component['dateRangeInvalid']()).toBe(true);
    expect(component['searchDisabled']()).toBe(true);
  });

  it('search() calls the store with ISO dates from the form', () => {
    const searchSpy = vi.spyOn(store, 'search').mockResolvedValue();
    component['form'].setValue({
      property_id: 2, room_type_id: 3, start: new Date('2026-10-01'), end: new Date('2026-10-03'),
      quantity: 1, adults: 2, children: 1,
    });

    component.search();

    expect(searchSpy).toHaveBeenCalledWith({
      property_id: 2, room_type_id: 3, start: '2026-10-01', end: '2026-10-03',
      quantity: 1, adults: 2, children: 1,
    });
  });

  it('does not call the store when the form is invalid', () => {
    const searchSpy = vi.spyOn(store, 'search');
    component.search();
    expect(searchSpy).not.toHaveBeenCalled();
  });

  it('renders a loading indicator while searching', () => {
    store.loading.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Searching');
  });

  it('renders the backend error message on search failure', () => {
    store.error.set({ status: 404, message: 'property not found.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('property not found.');
  });

  it('renders the results table once a result is present', () => {
    store.result.set({
      property_id: 1, room_type_id: 1, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: true, remaining_by_date: { '2026-10-01': 5 }, price: null, price_error: null,
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-availability-results-table')).toBeTruthy();
  });

  it('startReservation() navigates to /reservations/new carrying the selected result', () => {
    const navigateSpy = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    store.result.set({
      property_id: 1, room_type_id: 2, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: true, remaining_by_date: {}, price: null, price_error: null,
    });
    component['form'].patchValue({ adults: 2, children: 1 });

    component.startReservation();

    expect(navigateSpy).toHaveBeenCalledWith(['/reservations/new'], {
      state: { property_id: 1, room_type_id: 2, start: '2026-10-01', end: '2026-10-03', quantity: 1, adults: 2, children: 1 },
    });
  });

  it('startReservation() does nothing when the result is not sellable', () => {
    const navigateSpy = vi.spyOn(router, 'navigate');
    store.result.set({
      property_id: 1, room_type_id: 2, start: '2026-10-01', end: '2026-10-03', quantity: 1,
      sellable: false, remaining_by_date: {}, price: null, price_error: null,
    });

    component.startReservation();

    expect(navigateSpy).not.toHaveBeenCalled();
  });
});
