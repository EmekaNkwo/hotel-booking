import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ReservationApiService } from '../api/reservation-api.service';
import { Reservation, ReservationCreateRequest } from '../models/reservation.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';
import { LatestRequestGuard } from '../../../shared/utils/latest-request-guard';

/** Reservation state (signals only). Every mutation replaces `current` with
 * the backend's authoritative response — `status`/`hold_expiry_at`/pricing
 * are NEVER set locally, only ever copied verbatim from a server reply.
 *
 * R0.10: every method that writes `current` (`loadOne`/`create`/
 * `requestPayment`/`cancel`) shares one `currentGuard` — whichever call was
 * issued LAST wins regardless of resolution order, so a slow-to-resolve
 * `loadOne()` can never stomp a newer mutation's result (or vice versa).
 *
 * R1.1: the Store owns pagination state (`count`/`hasNextPage`/
 * `hasPreviousPage`/`currentPage`) straight from the backend's own
 * envelope — never a locally-computed page count. `loadList()` defaults to
 * page 1, so `applyFilters()`/`clearFilters()` callers (which never pass a
 * page) naturally reset pagination on every filter change. */
@Injectable({ providedIn: 'root' })
export class ReservationStore {
  private readonly api = inject(ReservationApiService);
  private readonly listGuard = new LatestRequestGuard();
  private readonly currentGuard = new LatestRequestGuard();
  private lastStatus: string | undefined;

  readonly list = signal<Reservation[]>([]);
  readonly listLoading = signal(false);
  readonly listError = signal<ApiError | null>(null);
  readonly count = signal(0);
  readonly currentPage = signal(1);
  readonly hasNextPage = signal(false);
  readonly hasPreviousPage = signal(false);

  readonly current = signal<Reservation | null>(null);
  readonly loading = signal(false);
  readonly error = signal<ApiError | null>(null);

  async loadList(status?: string, page = 1): Promise<void> {
    const token = this.listGuard.next();
    this.lastStatus = status;
    this.listLoading.set(true);
    this.listError.set(null);
    try {
      const response = await firstValueFrom(this.api.list(status, page));
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
    await this.loadList(this.lastStatus, this.currentPage() + 1);
  }

  async previousPage(): Promise<void> {
    if (!this.hasPreviousPage()) return;
    await this.loadList(this.lastStatus, this.currentPage() - 1);
  }

  /** Re-fetches the current page with the last-used filters — for refresh
   * actions that should preserve the user's place in the list. */
  async refresh(): Promise<void> {
    await this.loadList(this.lastStatus, this.currentPage());
  }

  async loadOne(id: number): Promise<void> {
    const token = this.currentGuard.next();
    this.loading.set(true);
    this.error.set(null);
    try {
      const result = await firstValueFrom(this.api.get(id));
      if (!this.currentGuard.isCurrent(token)) return;
      this.current.set(result);
    } catch (err) {
      if (!this.currentGuard.isCurrent(token)) return;
      this.current.set(null);
      this.error.set(fromHttpError(err));
    } finally {
      if (this.currentGuard.isCurrent(token)) this.loading.set(false);
    }
  }

  /** Returns the created reservation on success, or `null` on failure (the
   * error is left on `error()` for the caller to render — never assumed to
   * have succeeded). */
  async create(request: ReservationCreateRequest): Promise<Reservation | null> {
    const token = this.currentGuard.next();
    this.loading.set(true);
    this.error.set(null);
    try {
      const reservation = await firstValueFrom(this.api.create(request));
      if (this.currentGuard.isCurrent(token)) this.current.set(reservation);
      return reservation;
    } catch (err) {
      if (this.currentGuard.isCurrent(token)) this.error.set(fromHttpError(err));
      return null;
    } finally {
      if (this.currentGuard.isCurrent(token)) this.loading.set(false);
    }
  }

  async requestPayment(id: number): Promise<boolean> {
    const token = this.currentGuard.next();
    this.loading.set(true);
    this.error.set(null);
    try {
      const result = await firstValueFrom(this.api.requestPayment(id));
      if (this.currentGuard.isCurrent(token)) this.current.set(result);
      return true;
    } catch (err) {
      if (this.currentGuard.isCurrent(token)) this.error.set(fromHttpError(err));
      return false;
    } finally {
      if (this.currentGuard.isCurrent(token)) this.loading.set(false);
    }
  }

  async cancel(id: number, idempotencyKey: string): Promise<boolean> {
    const token = this.currentGuard.next();
    this.loading.set(true);
    this.error.set(null);
    try {
      const result = await firstValueFrom(this.api.cancel(id, idempotencyKey));
      if (this.currentGuard.isCurrent(token)) this.current.set(result);
      return true;
    } catch (err) {
      if (this.currentGuard.isCurrent(token)) this.error.set(fromHttpError(err));
      return false;
    } finally {
      if (this.currentGuard.isCurrent(token)) this.loading.set(false);
    }
  }

  clearCurrent(): void {
    this.currentGuard.next(); // any in-flight loadOne()/mutation becomes stale
    this.current.set(null);
    this.error.set(null);
  }
}
