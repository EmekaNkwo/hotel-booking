import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AvailabilityApiService } from '../api/availability-api.service';
import { PropertyApiService } from '../api/property-api.service';
import { RoomTypeApiService } from '../api/room-type-api.service';
import { AvailabilitySearchParams, AvailabilitySearchResult } from '../models/availability-search.model';
import { Property } from '../models/property.model';
import { RoomType } from '../models/room-type.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';

/** Availability search state (signals only). Every search REPLACES the
 * previous result wholesale — no merging of stale client state with new
 * server data, and no client-side price/availability computation. */
@Injectable({ providedIn: 'root' })
export class AvailabilityStore {
  private readonly api = inject(AvailabilityApiService);
  private readonly propertyApi = inject(PropertyApiService);
  private readonly roomTypeApi = inject(RoomTypeApiService);

  readonly properties = signal<Property[]>([]);
  readonly roomTypes = signal<RoomType[]>([]);
  readonly referenceDataLoading = signal(false);

  readonly lastSearch = signal<AvailabilitySearchParams | null>(null);
  readonly result = signal<AvailabilitySearchResult | null>(null);
  readonly loading = signal(false);
  readonly error = signal<ApiError | null>(null);

  async loadReferenceData(): Promise<void> {
    this.referenceDataLoading.set(true);
    try {
      const [properties, roomTypes] = await Promise.all([
        firstValueFrom(this.propertyApi.list()),
        firstValueFrom(this.roomTypeApi.list()),
      ]);
      this.properties.set(properties);
      this.roomTypes.set(roomTypes);
    } finally {
      this.referenceDataLoading.set(false);
    }
  }

  async search(params: AvailabilitySearchParams): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    this.lastSearch.set(params);
    try {
      const result = await firstValueFrom(this.api.search(params));
      this.result.set(result);
    } catch (err) {
      this.result.set(null);
      this.error.set(fromHttpError(err));
    } finally {
      this.loading.set(false);
    }
  }

  /** Re-runs the last search verbatim — used after a 409 tells the caller
   * availability may have changed, so the user can see the current truth
   * before retrying a reservation. Never mutates `result` optimistically. */
  async refresh(): Promise<void> {
    const params = this.lastSearch();
    if (params) {
      await this.search(params);
    }
  }

  clear(): void {
    this.result.set(null);
    this.error.set(null);
    this.lastSearch.set(null);
  }
}
