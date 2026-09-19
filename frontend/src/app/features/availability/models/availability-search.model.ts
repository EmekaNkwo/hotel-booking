import { PriceBreakdown } from './price-breakdown.model';

/** Matches `AvailabilitySearchSerializer` (apps/availability/api/serializers.py).
 * `start`/`end` are end-exclusive stay-period dates (ISO `yyyy-MM-dd`) — the
 * departure date is NOT charged/consumed, per the backend's `DateRange`/
 * `StayPeriod` value objects. */
export interface AvailabilitySearchParams {
  property_id: number;
  room_type_id: number;
  start: string;
  end: string;
  quantity: number;
  adults: number;
  children: number;
}

/** Matches `AvailabilitySearchView`'s response (apps/availability/api/views.py). */
export interface AvailabilitySearchResult {
  property_id: number;
  room_type_id: number;
  start: string;
  end: string;
  quantity: number;
  sellable: boolean;
  remaining_by_date: Record<string, number>;
  price: PriceBreakdown | null;
  price_error: string | null;
}
