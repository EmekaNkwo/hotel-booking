import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { PaginatedResponse } from '../../../shared/models/paginated-response.model';
import { NotificationJob, NotificationJobListFilters } from '../models/notification-job.model';

/** Thin, read-only wrapper over the Notifications HTTP surface
 * (apps/notifications/api, A0). No retry/requeue call exists here — A0
 * exposes none, and delivery stays Celery/projector-driven.
 *
 * R1.1: `list()` returns the full paginated envelope — never unwrapped. */
@Injectable({ providedIn: 'root' })
export class NotificationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(filters: NotificationJobListFilters = {}, page = 1): Observable<PaginatedResponse<NotificationJob>> {
    let params = new HttpParams().set('page', page);
    if (filters.status) {
      params = params.set('status', filters.status);
    }
    return this.http.get<PaginatedResponse<NotificationJob>>(`${this.base}/notifications/`, { params });
  }

  get(id: number): Observable<NotificationJob> {
    return this.http.get<NotificationJob>(`${this.base}/notifications/${id}/`);
  }
}
