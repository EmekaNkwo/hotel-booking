import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { PaginatedResponse } from '../../../shared/models/paginated-response.model';
import {
  CheckoutRequest,
  HousekeepingTask,
  HousekeepingTaskListFilters,
  InspectRequest,
} from '../models/housekeeping-task.model';

/** Thin wrapper over the Housekeeping HTTP surface (apps/housekeeping/api,
 * A0). Every mutation delegates entirely to `HousekeepingService` — this
 * service performs no room/task state computation of its own, and no
 * assignment call exists here since A0 exposes none over HTTP.
 *
 * R1.1: `list()` returns the full paginated envelope — never unwrapped. */
@Injectable({ providedIn: 'root' })
export class HousekeepingApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  checkout(request: CheckoutRequest): Observable<HousekeepingTask> {
    return this.http.post<HousekeepingTask>(`${this.base}/housekeeping/checkout/`, request);
  }

  list(filters: HousekeepingTaskListFilters = {}, page = 1): Observable<PaginatedResponse<HousekeepingTask>> {
    let params = new HttpParams().set('page', page);
    if (filters.status) {
      params = params.set('status', filters.status);
    }
    if (filters.room_id != null) {
      params = params.set('room_id', filters.room_id);
    }
    return this.http.get<PaginatedResponse<HousekeepingTask>>(`${this.base}/housekeeping/tasks/`, { params });
  }

  get(taskId: number): Observable<HousekeepingTask> {
    return this.http.get<HousekeepingTask>(`${this.base}/housekeeping/tasks/${taskId}/`);
  }

  startCleaning(taskId: number, idempotencyKey?: string): Observable<HousekeepingTask> {
    return this.http.post<HousekeepingTask>(
      `${this.base}/housekeeping/tasks/${taskId}/start-cleaning/`,
      { idempotency_key: idempotencyKey ?? '' },
    );
  }

  completeCleaning(taskId: number, idempotencyKey?: string): Observable<HousekeepingTask> {
    return this.http.post<HousekeepingTask>(
      `${this.base}/housekeeping/tasks/${taskId}/complete-cleaning/`,
      { idempotency_key: idempotencyKey ?? '' },
    );
  }

  inspect(taskId: number, request: InspectRequest): Observable<HousekeepingTask> {
    return this.http.post<HousekeepingTask>(
      `${this.base}/housekeeping/tasks/${taskId}/inspect/`,
      request,
    );
  }
}
