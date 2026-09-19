import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';

import { RoomDetailPage } from './room-detail-page';
import { RoomStore } from '../store/room.store';
import { Room } from '../models/room.model';

const ROOM: Room = {
  id: 7, code: '707', property_id: 3,
  room_type: { id: 2, code: 'DLX', name: 'Deluxe', status: 'active', max_occupancy: 4, attributes: { view: 'ocean' } },
  operational_state: 'occupied_dirty', current_booking_line_id: 12,
};

describe('RoomDetailPage', () => {
  let fixture: ComponentFixture<RoomDetailPage>;
  let store: RoomStore;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [RoomDetailPage],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: '7' }) } } },
      ],
    });
    fixture = TestBed.createComponent(RoomDetailPage);
    store = TestBed.inject(RoomStore);
    vi.spyOn(store, 'loadOne').mockResolvedValue();
    fixture.detectChanges();
  });

  it('loads the room by the route id on init', () => {
    expect(store.loadOne).toHaveBeenCalledWith(7);
  });

  it('renders the authoritative room fields and status badge once loaded', () => {
    store.current.set(ROOM);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('707');
    expect(text).toContain('Deluxe');
    expect(text).toContain('12');
    expect(fixture.nativeElement.querySelector('app-room-status-badge')).toBeTruthy();
  });

  it('renders room type attributes only when present', () => {
    store.current.set(ROOM);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('ocean');

    store.current.set({ ...ROOM, room_type: { ...ROOM.room_type, attributes: {} } });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('Room type attributes');
  });

  it('renders no state-transition controls (M3 owns transitions)', () => {
    store.current.set(ROOM);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('button')).toBeNull();
  });

  it('renders the backend error message on a detail failure', () => {
    store.current.set(null);
    store.detailError.set({ status: 404, message: 'room not found.', raw: null });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('room not found.');
  });
});
