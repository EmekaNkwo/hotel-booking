import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';

import { BookingDetailPage } from './booking-detail-page';
import { BookingStore } from '../store/booking.store';
import { Booking } from '../models/booking.model';
import { AllocationStore } from '../../allocation/store/allocation.store';
import { AllocationRecord } from '../../allocation/models/allocation-record.model';
import { HousekeepingStore } from '../../housekeeping/store/housekeeping.store';
import { HousekeepingTask } from '../../housekeeping/models/housekeeping-task.model';

const BOOKING: Booking = {
  id: 7, booking_ref: 'BR7', aggregate_status: 'pending_payment', currency: 'NGN',
  total_minor_units: 20000, arrival_date: '2026-10-01', departure_date: '2026-10-03',
  guest_profile_id: 1, reservation_id: 5,
  guest_snapshot: { name: { display_name: 'Jane Doe' }, email: 'jane@example.com', phone: null },
  lines: [
    { id: 1, line_no: 1, room_type_id: 2, room_id: null, arrival_date: '2026-10-01', departure_date: '2026-10-03', status: 'confirmed', price_snapshot: { nightly: [], stay_adjustments: [], subtotal_minor_units: 0, total_minor_units: 0, currency: 'NGN', floor_minor_units: null, ceiling_minor_units: null } },
    { id: 2, line_no: 2, room_type_id: 2, room_id: 101, arrival_date: '2026-10-01', departure_date: '2026-10-03', status: 'checked_in', price_snapshot: { nightly: [], stay_adjustments: [], subtotal_minor_units: 0, total_minor_units: 0, currency: 'NGN', floor_minor_units: null, ceiling_minor_units: null } },
  ],
  created_at: '2026-09-01T00:00:00Z',
};

describe('BookingDetailPage', () => {
  let fixture: ComponentFixture<BookingDetailPage>;
  let component: BookingDetailPage;
  let store: BookingStore;
  let allocationStore: AllocationStore;
  let housekeepingStore: HousekeepingStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [BookingDetailPage],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } } },
      ],
    });
    fixture = TestBed.createComponent(BookingDetailPage);
    component = fixture.componentInstance;
    store = TestBed.inject(BookingStore);
    allocationStore = TestBed.inject(AllocationStore);
    housekeepingStore = TestBed.inject(HousekeepingStore);
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the booking by the route id on init', () => {
    expect(store.loadOne).toHaveBeenCalledWith(7);
  });

  it('renders the authoritative booking reference/status once loaded', () => {
    store.current.set(BOOKING);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('BR7');
    expect(fixture.nativeElement.textContent).toContain('pending_payment');
  });

  it('renders the guest SNAPSHOT, distinct from any current guest profile', () => {
    store.current.set(BOOKING);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Jane Doe');
    expect(fixture.nativeElement.textContent).toContain('jane@example.com');
    expect(fixture.nativeElement.textContent).toContain('never updated from the guest');
  });

  it('shows the assigned room from room_id, or Unassigned when null', () => {
    store.current.set(BOOKING);
    fixture.detectChanges();
    const cells = Array.from(fixture.nativeElement.querySelectorAll('.lines-table td')).map(
      (el: unknown) => (el as HTMLElement).textContent?.trim(),
    );
    expect(cells).toContain('Unassigned');
    expect(cells).toContain('101');
  });

  it('renders the backend error message on a detail failure', () => {
    store.current.set(null);
    store.error.set({ status: 404, message: 'booking not found.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('booking not found.');
  });

  it('isAllocatable() is true only for confirmed lines with no room assigned', () => {
    expect(component.isAllocatable(BOOKING.lines[0])).toBe(true); // confirmed, room_id null
    expect(component.isAllocatable(BOOKING.lines[1])).toBe(false); // checked_in, room_id set
  });

  it('shows an Allocate action only for the allocatable line', () => {
    store.current.set(BOOKING);
    fixture.detectChanges();
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')).map(
      (b: unknown) => (b as HTMLElement).textContent?.trim(),
    );
    expect(buttons.filter((t) => t === 'Allocate').length).toBe(1);
  });

  it('allocate() success replaces booking state by reloading from the server (never a manual room_id set)', async () => {
    store.current.set(BOOKING);
    const record: AllocationRecord = {
      id: 1, booking_line_id: 1, room_id: 101, override: false, override_reason: '',
      criteria: {}, scores: {}, reason: 'only eligible room', created_at: '2026-09-01T00:00:00Z',
    };
    const allocateSpy = vi.spyOn(allocationStore, 'allocate').mockResolvedValue(record);
    const loadOneSpy = vi.mocked(store.loadOne).mockClear();

    await component.allocate(BOOKING.lines[0]);

    expect(allocateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ booking_line_id: 1, idempotency_key: expect.any(String) }),
    );
    expect(loadOneSpy).toHaveBeenCalledWith(7);
  });

  it('allocate() 409 does not reload the booking and reuses the same idempotency key on retry', async () => {
    store.current.set(BOOKING);
    const allocateSpy = vi.spyOn(allocationStore, 'allocate').mockImplementation(async () => {
      allocationStore.errorByLine.update((m) => ({ ...m, 1: { status: 409, message: 'no eligible room.', raw: null } }));
      return null;
    });
    const loadOneSpy = vi.mocked(store.loadOne).mockClear();

    await component.allocate(BOOKING.lines[0]);
    await component.allocate(BOOKING.lines[0]);
    fixture.detectChanges();

    expect(loadOneSpy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('no eligible room.');
    const firstKey = allocateSpy.mock.calls[0][0].idempotency_key;
    const secondKey = allocateSpy.mock.calls[1][0].idempotency_key;
    expect(firstKey).toBe(secondKey);
  });

  it('renders the allocation result transparently once returned, without recomputing it', () => {
    store.current.set(BOOKING);
    allocationStore.recordsByLine.set({
      1: { id: 1, booking_line_id: 1, room_id: 101, override: false, override_reason: '', criteria: {}, scores: {}, reason: 'only eligible room', created_at: '2026-09-01T00:00:00Z' },
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('only eligible room');
  });

  it('isCheckoutEligible() is true only for checked_in lines', () => {
    expect(component.isCheckoutEligible(BOOKING.lines[0])).toBe(false); // confirmed
    expect(component.isCheckoutEligible(BOOKING.lines[1])).toBe(true); // checked_in
  });

  it('shows a Check out action only for the checked_in line', () => {
    store.current.set(BOOKING);
    fixture.detectChanges();
    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')).map(
      (b: unknown) => (b as HTMLElement).textContent?.trim(),
    );
    expect(buttons.filter((t) => t === 'Check out').length).toBe(1);
  });

  it('checkout() success shows the returned task and reloads the booking (never a manual status/room mutation)', async () => {
    store.current.set(BOOKING);
    const task: HousekeepingTask = {
      id: 9, room_id: 101, booking_line_id: 2, business_date: '2026-10-03',
      task_kind: 'departure', status: 'planned', assignee_id: null, created_at: '2026-10-03T00:00:00Z',
    };
    const checkoutSpy = vi.spyOn(housekeepingStore, 'checkout').mockResolvedValue(task);
    const loadOneSpy = vi.mocked(store.loadOne).mockClear();

    await component.checkout(BOOKING.lines[1]);
    fixture.detectChanges();

    expect(checkoutSpy).toHaveBeenCalledWith(
      expect.objectContaining({ booking_line_id: 2, idempotency_key: expect.any(String) }),
    );
    expect(loadOneSpy).toHaveBeenCalledWith(7);
    expect(fixture.nativeElement.textContent).toContain('housekeeping task 9');
  });

  it('checkout() 409 does not reload the booking and reuses the same idempotency key on retry', async () => {
    store.current.set(BOOKING);
    const checkoutSpy = vi.spyOn(housekeepingStore, 'checkout').mockResolvedValue(null);
    const loadOneSpy = vi.mocked(store.loadOne).mockClear();

    await component.checkout(BOOKING.lines[1]);
    await component.checkout(BOOKING.lines[1]);

    expect(loadOneSpy).not.toHaveBeenCalled();
    const firstKey = checkoutSpy.mock.calls[0][0].idempotency_key;
    const secondKey = checkoutSpy.mock.calls[1][0].idempotency_key;
    expect(firstKey).toBe(secondKey);
  });
});
