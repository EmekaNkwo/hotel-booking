import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { PaginatedResponse } from '../../../shared/models/paginated-response.model';
import { Booking, BookingConfirmRequest } from '../models/booking.model';

/** Thin wrapper over the Bookings HTTP surface (apps/bookings/api, A0).
 * `BookingService.confirm()` performs the reservation conversion and
 * booking creation entirely server-side — this service never constructs a
 * Booking or computes a total itself.
 *
 * R1.1: `list()` returns the full paginated envelope — never unwrapped. */
@Injectable({ providedIn: 'root' })
export class BookingApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(status?: string, page = 1, arrivalDate?: string): Observable<PaginatedResponse<Booking>> {
    let params = new HttpParams().set('page', page);
    if (status) params = params.set('status', status);
    if (arrivalDate) params = params.set('arrival_date', arrivalDate);
    return this.http.get<PaginatedResponse<Booking>>(`${this.base}/bookings/`, { params });
  }

  get(id: number): Observable<Booking> {
    return this.http.get<Booking>(`${this.base}/bookings/${id}/`);
  }

  confirm(request: BookingConfirmRequest): Observable<Booking> {
    return this.http.post<Booking>(`${this.base}/bookings/confirm/`, request);
  }
}
