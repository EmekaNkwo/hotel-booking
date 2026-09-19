/** Matches `AllocationRecordSerializer` (apps/allocation/api/serializers.py).
 * `criteria`/`scores` are shown transparently, never recomputed — the
 * backend is the only source of allocation decisions. */
export interface AllocationRecord {
  id: number;
  booking_line_id: number;
  room_id: number;
  override: boolean;
  override_reason: string;
  criteria: Record<string, unknown>;
  scores: Record<string, unknown>;
  reason: string;
  created_at: string;
}

/** Matches `AllocateLineSerializer`'s input shape. */
export interface AllocateLineRequest {
  booking_line_id: number;
  idempotency_key?: string;
}
