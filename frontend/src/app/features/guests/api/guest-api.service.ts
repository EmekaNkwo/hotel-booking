import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { PaginatedResponse } from '../../../shared/models/paginated-response.model';
import { GuestProfile, GuestResolveRequest } from '../models/guest.model';

/** Thin wrapper over `GET /api/guests/`, `POST /api/guests/create/`
 * (apps/guests/api, A0). Creation delegates entirely to the backend's
 * `GuestService.resolve()` (find-or-create) — no identity logic here.
 *
 * R1.1: `search()` returns the full paginated envelope — never unwrapped. */
@Injectable({ providedIn: 'root' })
export class GuestApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  search(query: string, page = 1): Observable<PaginatedResponse<GuestProfile>> {
    let params = new HttpParams().set('page', page);
    if (query) params = params.set('q', query);
    return this.http.get<PaginatedResponse<GuestProfile>>(`${this.base}/guests/`, { params });
  }

  resolve(request: GuestResolveRequest): Observable<GuestProfile> {
    return this.http.post<GuestProfile>(`${this.base}/guests/create/`, request);
  }

  get(id: number): Observable<GuestProfile> {
    return this.http.get<GuestProfile>(`${this.base}/guests/${id}/`);
  }
}
