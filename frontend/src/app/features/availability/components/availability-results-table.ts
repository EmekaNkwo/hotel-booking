import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTableModule } from '@angular/material/table';

import { AvailabilitySearchResult } from '../models/availability-search.model';

interface NightRow {
  night: string;
  remaining: number;
}

/** Dense, single-result operational table: remaining units per night plus
 * the backend's own price breakdown. Renders exactly what the API returned
 * — no client-side pricing or availability computation. */
@Component({
  selector: 'app-availability-results-table',
  imports: [MatButtonModule, MatIconModule, MatTableModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './availability-results-table.html',
  styleUrl: './availability-results-table.scss',
})
export class AvailabilityResultsTable {
  readonly result = input.required<AvailabilitySearchResult>();
  readonly reserve = output<void>();

  protected readonly nightColumns = ['night', 'remaining'];
  protected readonly nightRows = computed<NightRow[]>(() =>
    Object.entries(this.result().remaining_by_date)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([night, remaining]) => ({ night, remaining })),
  );

  // Assumes a 2-decimal minor unit (true for every currency this tenant
  // seed data uses, NGN/USD) — the backend's own PriceBreakdown doesn't
  // carry a decimal-places field, so this display-only conversion mirrors
  // what A0's other minor-units fields already assume.
  protected formatMoney(minorUnits: number, currency: string): string {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(
      minorUnits / 100,
    );
  }
}
