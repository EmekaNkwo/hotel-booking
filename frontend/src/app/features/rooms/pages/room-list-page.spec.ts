import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { RoomListPage } from './room-list-page';
import { RoomStore } from '../store/room.store';
import { Room } from '../models/room.model';

const ROOM: Room = {
  id: 1, code: '101', property_id: 1,
  room_type: { id: 1, code: 'STD', name: 'Standard', status: 'active', max_occupancy: 2, attributes: {} },
  operational_state: 'vacant_clean', current_booking_line_id: null,
};

describe('RoomListPage', () => {
  let fixture: ComponentFixture<RoomListPage>;
  let component: RoomListPage;
  let store: RoomStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [RoomListPage, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    fixture = TestBed.createComponent(RoomListPage);
    component = fixture.componentInstance;
    store = TestBed.inject(RoomStore);
    vi.spyOn(store, 'loadReferenceData').mockResolvedValue();
    vi.spyOn(store, 'loadList').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads reference data and the unfiltered room list on init', () => {
    expect(store.loadReferenceData).toHaveBeenCalled();
    expect(store.loadList).toHaveBeenCalledWith();
  });

  it('shows a loading indicator while the list request is in flight', () => {
    store.listLoading.set(true);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Loading');
  });

  it('shows an empty state when there are no rooms', () => {
    store.list.set([]);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-empty-state')).toBeTruthy();
  });

  it('renders a row per room, including its status badge', () => {
    store.list.set([ROOM]);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('101');
    expect(fixture.nativeElement.querySelector('app-room-status-badge')).toBeTruthy();
  });

  it('renders the backend error message on a list failure', () => {
    store.listError.set({ status: 403, message: 'not allowed.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('not allowed.');
  });

  it('applyFilters() re-issues loadList with the current form values (server-side filtering)', () => {
    component['filterForm'].setValue({ property_id: 2, room_type_id: null, operational_state: 'vacant_clean' });

    component.applyFilters();

    expect(store.loadList).toHaveBeenCalledWith({
      property_id: 2, room_type_id: undefined, operational_state: 'vacant_clean',
    });
  });

  it('clearFilters() resets the form and reloads with no filters', () => {
    component['filterForm'].setValue({ property_id: 2, room_type_id: null, operational_state: 'vacant_clean' });

    component.clearFilters();

    expect(component['filterForm'].getRawValue()).toEqual({
      property_id: null, room_type_id: null, operational_state: null,
    });
    expect(store.loadList).toHaveBeenLastCalledWith({});
  });

  it('hasActiveFilters() reflects whether any filter is set', () => {
    expect(component['hasActiveFilters']()).toBe(false);
    component['filterForm'].patchValue({ property_id: 1 });
    expect(component['hasActiveFilters']()).toBe(true);
  });
});
