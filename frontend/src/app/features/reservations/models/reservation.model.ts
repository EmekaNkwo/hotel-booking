import { PriceBreakdown } from '../../availability/models/price-breakdown.model';

/** The reservation lifecycle states the backend can return (Reservation FSM,
 * apps/reservations/models.py). Rendered verbatim — never computed here. */
export type ReservationStatus =
  | 'draft'
  | 'held'
  | 'awaiting_payment'
  | 'converted'
  | 'expired'
  | 'cancelled';

/** Matches `ReservationLineInputSerializer` (apps/reservations/api/serializers.py). */
export interface ReservationLineInput {
  room_type_id: number;
  arrival_date: string;
  departure_date: string;
  adults: number;
  children: number;
  quantity: number;
}

/** Matches `ReservationCreateSerializer`'s input shape. */
export interface ReservationCreateRequest {
  property_id: number;
  guest_email?: string | null;
  guest_phone?: string | null;
  lines: ReservationLineInput[];
  idempotency_key?: string;
}

/** Matches `ReservationLineSerializer` (read model). */
export interface ReservationLine {
  id: number;
  line_no: number;
  room_type_id: number;
  arrival_date: string;
  departure_date: string;
  quantity: number;
  price_snapshot: PriceBreakdown;
}

/** Matches `ReservationSerializer` (apps/reservations/api/serializers.py). */
export interface Reservation {
  id: number;
  reservation_ref: string;
  status: ReservationStatus;
  channel: string;
  hold_expiry_at: string | null;
  price_snapshot: Record<string, unknown>;
  policy_snapshot: Record<string, unknown>;
  guest_profile_id: number | null;
  property_id: number;
  lines: ReservationLine[];
  created_at: string;
}
