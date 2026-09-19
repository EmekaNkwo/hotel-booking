/** Matches `RoomTypeSerializer` (apps/rooms/api/serializers.py, A0). */
export interface RoomType {
  id: number;
  code: string;
  name: string;
  status: string;
  max_occupancy: number;
  attributes: Record<string, unknown>;
}
