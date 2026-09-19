import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { RoomApiService } from '../api/room-api.service';
import { PropertyApiService } from '../../availability/api/property-api.service';
import { RoomTypeApiService } from '../../availability/api/room-type-api.service';
import { Room, RoomListFilters } from '../models/room.model';
import { Property } from '../../availability/models/property.model';
import { RoomType } from '../../availability/models/room-type.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';
import { LatestRequestGuard } from '../../../shared/utils/latest-request-guard';

/** Room board state (signals only). Every list load REPLACES the previous
 * result wholesale from the server's own filtered query — no client-side
 * business filtering over an unbounded dataset, and no derived/simulated
 * room state. Reuses A2's Property/RoomType reference-data services rather
 * than duplicating them.
 *
 * R0.10: `listGuard`/`detailGuard` ensure a stale, late-resolving
 * `loadList()`/`loadOne()` (e.g. from a filter change or navigating away
 * before the previous call finished) can never overwrite a newer one. */
@Injectable({ providedIn: 'root' })
export class RoomStore {
  private readonly api = inject(RoomApiService);
  private readonly propertyApi = inject(PropertyApiService);
  private readonly roomTypeApi = inject(RoomTypeApiService);
  private readonly listGuard = new LatestRequestGuard();
  private readonly detailGuard = new LatestRequestGuard();

  readonly properties = signal<Property[]>([]);
  readonly roomTypes = signal<RoomType[]>([]);
  readonly referenceDataLoading = signal(false);

  readonly filters = signal<RoomListFilters>({});
  readonly list = signal<Room[]>([]);
  readonly listLoading = signal(false);
  readonly listError = signal<ApiError | null>(null);
  readonly count = signal(0);
  readonly currentPage = signal(1);
  readonly hasNextPage = signal(false);
  readonly hasPreviousPage = signal(false);

  readonly current = signal<Room | null>(null);
  readonly detailLoading = signal(false);
  readonly detailError = signal<ApiError | null>(null);

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

  async loadList(filters: RoomListFilters = {}, page = 1): Promise<void> {
    const token = this.listGuard.next();
    this.filters.set(filters);
    this.listLoading.set(true);
    this.listError.set(null);
    try {
      const response = await firstValueFrom(this.api.list(filters, page));
      if (!this.listGuard.isCurrent(token)) return;
      this.list.set(response.results);
      this.count.set(response.count);
      this.currentPage.set(page);
      this.hasNextPage.set(response.next !== null);
      this.hasPreviousPage.set(response.previous !== null);
    } catch (err) {
      if (!this.listGuard.isCurrent(token)) return;
      this.list.set([]);
      this.count.set(0);
      this.hasNextPage.set(false);
      this.hasPreviousPage.set(false);
      this.listError.set(fromHttpError(err));
    } finally {
      if (this.listGuard.isCurrent(token)) this.listLoading.set(false);
    }
  }

  async nextPage(): Promise<void> {
    if (!this.hasNextPage()) return;
    await this.loadList(this.filters(), this.currentPage() + 1);
  }

  async previousPage(): Promise<void> {
    if (!this.hasPreviousPage()) return;
    await this.loadList(this.filters(), this.currentPage() - 1);
  }

  async refresh(): Promise<void> {
    await this.loadList(this.filters(), this.currentPage());
  }

  async loadOne(id: number): Promise<void> {
    const token = this.detailGuard.next();
    this.detailLoading.set(true);
    this.detailError.set(null);
    try {
      const result = await firstValueFrom(this.api.get(id));
      if (!this.detailGuard.isCurrent(token)) return;
      this.current.set(result);
    } catch (err) {
      if (!this.detailGuard.isCurrent(token)) return;
      this.current.set(null);
      this.detailError.set(fromHttpError(err));
    } finally {
      if (this.detailGuard.isCurrent(token)) this.detailLoading.set(false);
    }
  }
}
