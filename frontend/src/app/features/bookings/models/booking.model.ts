import { PriceBreakdown } from '../../availability/models/price-breakdown.model';

/** Matches `BookingLineSerializer` (apps/bookings/api/serializers.py). */
export interface BookingLine {
  id: number;
  line_no: number;
  room_type_id: number;
  room_id: number | null;
  arrival_date: string;
  departure_date: string;
  status: string;
  price_snapshot: PriceBreakdown;
}

/** The guest identity captured verbatim at confirm time (DMS invariant #8:
 * a later profile merge must never rewrite booking history) — deliberately
 * a separate shape from `GuestProfile`, never reconciled with it. */
export interface GuestSnapshot {
  name?: Record<string, string>;
  email?: string | null;
  phone?: string | null;
}

/** Matches `BookingSerializer` (apps/bookings/api/serializers.py). */
export interface Booking {
  id: number;
  booking_ref: string;
  aggregate_status: string;
  currency: string;
  total_minor_units: number;
  arrival_date: string;
  departure_date: string;
  guest_profile_id: number | null;
  reservation_id: number | null;
  guest_snapshot: GuestSnapshot;
  lines: BookingLine[];
  created_at: string;
}

/** Matches `BookingConfirmSerializer`'s input shape. */
export interface BookingConfirmRequest {
  reservation_id: number;
  idempotency_key?: string;
}
