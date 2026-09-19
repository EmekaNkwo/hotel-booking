import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { AvailabilitySearchParams, AvailabilitySearchResult } from '../models/availability-search.model';

/** Thin wrapper over `GET /api/availability/` (apps/availability/api, A0).
 * No client-side pricing/availability computation — the backend response is
 * rendered verbatim. */
@Injectable({ providedIn: 'root' })
export class AvailabilityApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  search(params: AvailabilitySearchParams): Observable<AvailabilitySearchResult> {
    let httpParams = new HttpParams();
    for (const [key, value] of Object.entries(params)) {
      httpParams = httpParams.set(key, String(value));
    }
    return this.http.get<AvailabilitySearchResult>(`${this.base}/availability/`, {
      params: httpParams,
    });
  }
}
