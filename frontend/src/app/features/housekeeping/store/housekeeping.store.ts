import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { HousekeepingApiService } from '../api/housekeeping-api.service';
import {
  CheckoutRequest,
  HousekeepingTask,
  HousekeepingTaskListFilters,
  InspectRequest,
} from '../models/housekeeping-task.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';
import { LatestRequestGuard } from '../../../shared/utils/latest-request-guard';

/** Housekeeping state (signals only). Every task field comes straight from
 * a server response — `status` is never transitioned locally, and a
 * concurrency/state 409 leaves `current`/`tasks` exactly as last loaded
 * from the backend. Checkout state is keyed by `booking_line_id` (invoked
 * from booking detail, before any task exists); task-action state is keyed
 * by `task_id` — kept separate so one operation never wipes the other's
 * loading/error UI.
 *
 * R0.10: `loadOne()` and every task-transition action (they all funnel
 * through `runAction()`) write `current` and share `currentGuard` — the
 * last-ISSUED call wins regardless of resolution order. `listGuard`
 * protects `tasks` the same way for `loadList()`.
 *
 * R1.2: `currentGuard` alone only protected `current` — `tasks.update()`,
 * `actionErrorByTask`, and `actionLoadingByTask` could still be written by
 * a stale, late-resolving action even after a newer action for the SAME
 * task had already completed. `runAction()` now also takes a token from a
 * PER-TASK guard (`actionGuardFor(taskId)`) and gates those three writes
 * on it — so for a given task, only the latest-issued command can modify
 * that task's list entry/error/loading state, without one task's action
 * spuriously invalidating an unrelated task's concurrent action (which a
 * single shared guard would have done). */
@Injectable({ providedIn: 'root' })
export class HousekeepingStore {
  private readonly api = inject(HousekeepingApiService);
  private readonly listGuard = new LatestRequestGuard();
  private readonly currentGuard = new LatestRequestGuard();
  private readonly actionGuards = new Map<number, LatestRequestGuard>();

  readonly tasks = signal<HousekeepingTask[]>([]);
  readonly listLoading = signal(false);
  readonly listError = signal<ApiError | null>(null);
  readonly count = signal(0);
  readonly currentPage = signal(1);
  readonly hasNextPage = signal(false);
  readonly hasPreviousPage = signal(false);
  private lastFilters: HousekeepingTaskListFilters = {};

  readonly current = signal<HousekeepingTask | null>(null);
  readonly detailLoading = signal(false);
  readonly detailError = signal<ApiError | null>(null);

  private readonly checkoutLoadingByLine = signal<Record<number, boolean>>({});
  private readonly checkoutErrorByLine = signal<Record<number, ApiError | null>>({});
  private readonly actionLoadingByTask = signal<Record<number, boolean>>({});
  private readonly actionErrorByTask = signal<Record<number, ApiError | null>>({});

  isCheckoutLoading(bookingLineId: number): boolean {
    return this.checkoutLoadingByLine()[bookingLineId] ?? false;
  }

  checkoutErrorFor(bookingLineId: number): ApiError | null {
    return this.checkoutErrorByLine()[bookingLineId] ?? null;
  }

  isActionLoading(taskId: number): boolean {
    return this.actionLoadingByTask()[taskId] ?? false;
  }

  actionErrorFor(taskId: number): ApiError | null {
    return this.actionErrorByTask()[taskId] ?? null;
  }

  async loadList(filters: HousekeepingTaskListFilters = {}, page = 1): Promise<void> {
    const token = this.listGuard.next();
    this.lastFilters = filters;
    this.listLoading.set(true);
    this.listError.set(null);
    try {
      const response = await firstValueFrom(this.api.list(filters, page));
      if (!this.listGuard.isCurrent(token)) return;
      this.tasks.set(response.results);
      this.count.set(response.count);
      this.currentPage.set(page);
      this.hasNextPage.set(response.next !== null);
      this.hasPreviousPage.set(response.previous !== null);
    } catch (err) {
      if (!this.listGuard.isCurrent(token)) return;
      this.tasks.set([]);
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

  async loadOne(taskId: number): Promise<void> {
    const token = this.currentGuard.next();
    this.detailLoading.set(true);
    this.detailError.set(null);
    try {
      const result = await firstValueFrom(this.api.get(taskId));
      if (!this.currentGuard.isCurrent(token)) return;
      this.current.set(result);
    } catch (err) {
      if (!this.currentGuard.isCurrent(token)) return;
      this.current.set(null);
      this.detailError.set(fromHttpError(err));
    } finally {
      if (this.currentGuard.isCurrent(token)) this.detailLoading.set(false);
    }
  }

  async checkout(request: CheckoutRequest): Promise<HousekeepingTask | null> {
    const lineId = request.booking_line_id;
    this.checkoutLoadingByLine.update((m) => ({ ...m, [lineId]: true }));
    this.checkoutErrorByLine.update((m) => ({ ...m, [lineId]: null }));
    try {
      return await firstValueFrom(this.api.checkout(request));
    } catch (err) {
      this.checkoutErrorByLine.update((m) => ({ ...m, [lineId]: fromHttpError(err) }));
      return null;
    } finally {
      this.checkoutLoadingByLine.update((m) => ({ ...m, [lineId]: false }));
    }
  }

  async startCleaning(taskId: number, idempotencyKey?: string): Promise<boolean> {
    return this.runAction(taskId, () => this.api.startCleaning(taskId, idempotencyKey));
  }

  async completeCleaning(taskId: number, idempotencyKey?: string): Promise<boolean> {
    return this.runAction(taskId, () => this.api.completeCleaning(taskId, idempotencyKey));
  }

  async inspect(taskId: number, request: InspectRequest): Promise<boolean> {
    return this.runAction(taskId, () => this.api.inspect(taskId, request));
  }

  private actionGuardFor(taskId: number): LatestRequestGuard {
    let guard = this.actionGuards.get(taskId);
    if (!guard) {
      guard = new LatestRequestGuard();
      this.actionGuards.set(taskId, guard);
    }
    return guard;
  }

  private async runAction(
    taskId: number,
    call: () => ReturnType<HousekeepingApiService['startCleaning']>,
  ): Promise<boolean> {
    const currentToken = this.currentGuard.next();
    const actionGuard = this.actionGuardFor(taskId);
    const actionToken = actionGuard.next();
    this.actionLoadingByTask.update((m) => ({ ...m, [taskId]: true }));
    this.actionErrorByTask.update((m) => ({ ...m, [taskId]: null }));
    try {
      const task = await firstValueFrom(call());
      if (this.currentGuard.isCurrent(currentToken)) this.current.set(task);
      if (actionGuard.isCurrent(actionToken)) {
        this.tasks.update((list) => list.map((t) => (t.id === task.id ? task : t)));
      }
      return true;
    } catch (err) {
      if (actionGuard.isCurrent(actionToken)) {
        this.actionErrorByTask.update((m) => ({ ...m, [taskId]: fromHttpError(err) }));
      }
      return false;
    } finally {
      if (actionGuard.isCurrent(actionToken)) {
        this.actionLoadingByTask.update((m) => ({ ...m, [taskId]: false }));
      }
    }
  }
}
