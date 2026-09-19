import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { GuestApiService } from '../api/guest-api.service';
import { GuestProfile, GuestResolveRequest } from '../models/guest.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';
import { LatestRequestGuard } from '../../../shared/utils/latest-request-guard';

/** Guest state (signals only) — shared by the embedded `GuestSearch`
 * component (reservation creation, A2: search/resolve) and the standalone
 * `/guests` screens (A3: list/detail). One store per the app's
 * one-store-per-feature convention; `loading`/`error` are scoped to
 * search+resolve, `detailLoading`/`detailError` to the detail screen, so
 * the two contexts never flicker each other's UI.
 *
 * R0.10: `search()` writes `searchResults`, `resolve()` writes
 * `selectedGuest`, and `loadOne()` writes `current` — three independent
 * signals, so each gets its own `LatestRequestGuard` (a stale response for
 * one can never race a stale response for another). */
@Injectable({ providedIn: 'root' })
export class GuestStore {
  private readonly api = inject(GuestApiService);
  private readonly searchGuard = new LatestRequestGuard();
  private readonly resolveGuard = new LatestRequestGuard();
  private readonly detailGuard = new LatestRequestGuard();
  private lastQuery = '';

  readonly searchResults = signal<GuestProfile[]>([]);
  readonly selectedGuest = signal<GuestProfile | null>(null);
  readonly loading = signal(false);
  readonly error = signal<ApiError | null>(null);
  readonly count = signal(0);
  readonly currentPage = signal(1);
  readonly hasNextPage = signal(false);
  readonly hasPreviousPage = signal(false);

  readonly current = signal<GuestProfile | null>(null);
  readonly detailLoading = signal(false);
  readonly detailError = signal<ApiError | null>(null);

  async search(query: string, page = 1): Promise<void> {
    const token = this.searchGuard.next();
    this.lastQuery = query;
    this.loading.set(true);
    this.error.set(null);
    try {
      const response = await firstValueFrom(this.api.search(query, page));
      if (!this.searchGuard.isCurrent(token)) return;
      this.searchResults.set(response.results);
      this.count.set(response.count);
      this.currentPage.set(page);
      this.hasNextPage.set(response.next !== null);
      this.hasPreviousPage.set(response.previous !== null);
    } catch (err) {
      if (!this.searchGuard.isCurrent(token)) return;
      this.searchResults.set([]);
      this.count.set(0);
      this.hasNextPage.set(false);
      this.hasPreviousPage.set(false);
      this.error.set(fromHttpError(err));
    } finally {
      if (this.searchGuard.isCurrent(token)) this.loading.set(false);
    }
  }

  async nextPage(): Promise<void> {
    if (!this.hasNextPage()) return;
    await this.search(this.lastQuery, this.currentPage() + 1);
  }

  async previousPage(): Promise<void> {
    if (!this.hasPreviousPage()) return;
    await this.search(this.lastQuery, this.currentPage() - 1);
  }

  async resolve(request: GuestResolveRequest): Promise<GuestProfile | null> {
    const token = this.resolveGuard.next();
    this.loading.set(true);
    this.error.set(null);
    try {
      const guest = await firstValueFrom(this.api.resolve(request));
      if (this.resolveGuard.isCurrent(token)) this.selectedGuest.set(guest);
      return guest;
    } catch (err) {
      if (this.resolveGuard.isCurrent(token)) this.error.set(fromHttpError(err));
      return null;
    } finally {
      if (this.resolveGuard.isCurrent(token)) this.loading.set(false);
    }
  }

  select(guest: GuestProfile): void {
    this.selectedGuest.set(guest);
  }

  clearSelection(): void {
    this.selectedGuest.set(null);
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
