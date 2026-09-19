import { RoomType } from '../../availability/models/room-type.model';

/** The exact M3 operational-state enum (apps/rooms/models.py). No
 * frontend-only state is ever introduced — render whichever of these eight
 * values the backend returns. */
export type RoomOperationalState =
  | 'vacant_clean'
  | 'vacant_dirty'
  | 'occupied_clean'
  | 'occupied_dirty'
  | 'out_of_service'
  | 'out_of_order'
  | 'cleaning'
  | 'inspected';

/** Matches `RoomSerializer` (apps/rooms/api/serializers.py). */
export interface Room {
  id: number;
  code: string;
  property_id: number;
  room_type: RoomType;
  operational_state: RoomOperationalState;
  current_booking_line_id: number | null;
}

/** `GET /api/rooms/`'s optional server-side filters — the only ones the
 * backend supports (apps/rooms/api/views.py). */
export interface RoomListFilters {
  property_id?: number;
  room_type_id?: number;
  operational_state?: RoomOperationalState;
}
