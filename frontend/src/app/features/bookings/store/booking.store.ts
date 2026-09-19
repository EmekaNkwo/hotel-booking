import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { BookingApiService } from '../api/booking-api.service';
import { Booking, BookingConfirmRequest } from '../models/booking.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';
import { LatestRequestGuard } from '../../../shared/utils/latest-request-guard';

/** Booking state (signals only). `confirm()` never assumes success from a
 * 200-family status alone — the caller gets the actual parsed `Booking`
 * back (or `null` on failure with `error()` populated), and `current` is
 * only ever replaced with what the server returned. No booking total,
 * status, or line is ever computed here.
 *
 * R0.10: `loadOne()` and `confirm()` both write `current` and share
 * `currentGuard` — whichever call was issued LAST (not whichever resolves
 * first) is the only one allowed to apply its result, so navigating away
 * mid-request or a slow `loadOne()` racing a `confirm()` can never leave a
 * stale value displayed under a newer id/state. `loadList()` has its own
 * `listGuard` for the same reason on `list`. */
@Injectable({ providedIn: 'root' })
export class BookingStore {
  private readonly api = inject(BookingApiService);
  private readonly listGuard = new LatestRequestGuard();
  private readonly currentGuard = new LatestRequestGuard();
  private lastStatus: string | undefined;

  readonly list = signal<Booking[]>([]);
  readonly listLoading = signal(false);
  readonly listError = signal<ApiError | null>(null);
  readonly count = signal(0);
  readonly currentPage = signal(1);
  readonly hasNextPage = signal(false);
  readonly hasPreviousPage = signal(false);

  readonly current = signal<Booking | null>(null);
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

  async confirm(request: BookingConfirmRequest): Promise<Booking | null> {
    const token = this.currentGuard.next();
    this.loading.set(true);
    this.error.set(null);
    try {
      const booking = await firstValueFrom(this.api.confirm(request));
      if (this.currentGuard.isCurrent(token)) this.current.set(booking);
      return booking;
    } catch (err) {
      if (this.currentGuard.isCurrent(token)) this.error.set(fromHttpError(err));
      return null;
    } finally {
      if (this.currentGuard.isCurrent(token)) this.loading.set(false);
    }
  }

  clearCurrent(): void {
    this.currentGuard.next(); // any in-flight loadOne()/confirm() becomes stale
    this.current.set(null);
    this.error.set(null);
  }
}
