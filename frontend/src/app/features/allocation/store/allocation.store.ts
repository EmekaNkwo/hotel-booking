import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AllocationApiService } from '../api/allocation-api.service';
import { AllocateLineRequest, AllocationRecord } from '../models/allocation-record.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';

/** Allocation command state, keyed by `booking_line_id` (signals only) — a
 * booking can have several lines, each allocated independently. Never sets
 * a room assignment locally: `allocate()` returns the server's
 * `AllocationRecord` (or `null` on failure with the per-line error
 * populated), and the caller (booking detail) is responsible for reloading
 * the authoritative `Booking` from `BookingStore` afterward. */
@Injectable({ providedIn: 'root' })
export class AllocationStore {
  private readonly api = inject(AllocationApiService);

  readonly recordsByLine = signal<Record<number, AllocationRecord>>({});
  readonly loadingByLine = signal<Record<number, boolean>>({});
  readonly errorByLine = signal<Record<number, ApiError | null>>({});

  isLoading(bookingLineId: number): boolean {
    return this.loadingByLine()[bookingLineId] ?? false;
  }

  errorFor(bookingLineId: number): ApiError | null {
    return this.errorByLine()[bookingLineId] ?? null;
  }

  async allocate(request: AllocateLineRequest): Promise<AllocationRecord | null> {
    const lineId = request.booking_line_id;
    this.loadingByLine.update((m) => ({ ...m, [lineId]: true }));
    this.errorByLine.update((m) => ({ ...m, [lineId]: null }));
    try {
      const record = await firstValueFrom(this.api.allocate(request));
      this.recordsByLine.update((m) => ({ ...m, [lineId]: record }));
      return record;
    } catch (err) {
      this.errorByLine.update((m) => ({ ...m, [lineId]: fromHttpError(err) }));
      return null;
    } finally {
      this.loadingByLine.update((m) => ({ ...m, [lineId]: false }));
    }
  }
}
