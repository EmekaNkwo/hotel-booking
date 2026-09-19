/** Matches `PriceBreakdown.to_dict()` (apps/shared/value_objects) — the same
 * snapshot shape returned by availability search and embedded verbatim in
 * a Reservation's `price_snapshot`. Never recomputed client-side. */
export interface NightlyPrice {
  night: string;
  base_minor_units: number;
  currency: string;
  adjustments: unknown[];
  total_minor_units: number;
}

export interface PriceBreakdown {
  nightly: NightlyPrice[];
  stay_adjustments: unknown[];
  subtotal_minor_units: number;
  total_minor_units: number;
  currency: string;
  floor_minor_units: number | null;
  ceiling_minor_units: number | null;
}
