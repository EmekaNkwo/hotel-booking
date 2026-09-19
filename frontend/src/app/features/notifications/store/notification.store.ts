import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { NotificationApiService } from '../api/notification-api.service';
import { NotificationJob, NotificationJobListFilters } from '../models/notification-job.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';
import { LatestRequestGuard } from '../../../shared/utils/latest-request-guard';

/** Notification state (signals only). Entirely read-only — no mutation
 * method exists here because A0 exposes none (delivery/retry stays
 * Celery/projector-driven, M13).
 *
 * R0.10: `listGuard`/`detailGuard` stop a stale, late-resolving
 * `loadList()`/`loadOne()` from overwriting a newer one. */
@Injectable({ providedIn: 'root' })
export class NotificationStore {
  private readonly api = inject(NotificationApiService);
  private readonly listGuard = new LatestRequestGuard();
  private readonly detailGuard = new LatestRequestGuard();

  readonly jobs = signal<NotificationJob[]>([]);
  readonly listLoading = signal(false);
  readonly listError = signal<ApiError | null>(null);
  readonly count = signal(0);
  readonly currentPage = signal(1);
  readonly hasNextPage = signal(false);
  readonly hasPreviousPage = signal(false);
  private lastFilters: NotificationJobListFilters = {};

  readonly current = signal<NotificationJob | null>(null);
  readonly detailLoading = signal(false);
  readonly detailError = signal<ApiError | null>(null);

  async loadList(filters: NotificationJobListFilters = {}, page = 1): Promise<void> {
    const token = this.listGuard.next();
    this.lastFilters = filters;
    this.listLoading.set(true);
    this.listError.set(null);
    try {
      const response = await firstValueFrom(this.api.list(filters, page));
      if (!this.listGuard.isCurrent(token)) return;
      this.jobs.set(response.results);
      this.count.set(response.count);
      this.currentPage.set(page);
      this.hasNextPage.set(response.next !== null);
      this.hasPreviousPage.set(response.previous !== null);
    } catch (err) {
      if (!this.listGuard.isCurrent(token)) return;
      this.jobs.set([]);
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
    await this.loadList(this.lastFilters, this.currentPage() + 1);
  }

  async previousPage(): Promise<void> {
    if (!this.hasPreviousPage()) return;
    await this.loadList(this.lastFilters, this.currentPage() - 1);
  }

  async refresh(): Promise<void> {
    await this.loadList(this.lastFilters, this.currentPage());
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
