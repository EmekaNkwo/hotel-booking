import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { PaginatedResponse } from '../../../shared/models/paginated-response.model';
import { Reservation, ReservationCreateRequest } from '../models/reservation.model';

/** Thin wrapper over the Reservations HTTP surface (apps/reservations/api,
 * A0; the list endpoint is A2's addition to it — see
 * `ReservationListCreateView`'s docstring). Every mutation returns the
 * backend's authoritative Reservation — nothing here infers or assumes a
 * resulting status.
 *
 * R1.1: `list()` returns the full `{count, next, previous, results}`
 * envelope — never unwrapped — so the Store can own real pagination state
 * instead of only ever seeing page 1. */
@Injectable({ providedIn: 'root' })
export class ReservationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(status?: string, page = 1): Observable<PaginatedResponse<Reservation>> {
    let params = new HttpParams().set('page', page);
    if (status) params = params.set('status', status);
    return this.http.get<PaginatedResponse<Reservation>>(`${this.base}/reservations/`, { params });
  }

  create(request: ReservationCreateRequest): Observable<Reservation> {
    return this.http.post<Reservation>(`${this.base}/reservations/`, request);
  }

  get(id: number): Observable<Reservation> {
    return this.http.get<Reservation>(`${this.base}/reservations/${id}/`);
  }

  requestPayment(id: number): Observable<Reservation> {
    return this.http.post<Reservation>(`${this.base}/reservations/${id}/request-payment/`, {});
  }

  cancel(id: number, idempotencyKey: string): Observable<Reservation> {
    return this.http.post<Reservation>(`${this.base}/reservations/${id}/cancel/`, {
      idempotency_key: idempotencyKey,
    });
  }
}
