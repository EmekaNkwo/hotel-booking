import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { PaginatedResponse } from '../../../shared/models/paginated-response.model';
import { Room, RoomListFilters } from '../models/room.model';

/** Thin wrapper over `GET /api/rooms/`, `GET /api/rooms/:id/`
 * (apps/rooms/api, A0). Filtering is server-side only — exactly the three
 * query params the backend supports.
 *
 * R1.1: `list()` returns the full paginated envelope — never unwrapped. */
@Injectable({ providedIn: 'root' })
export class RoomApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(filters: RoomListFilters = {}, page = 1): Observable<PaginatedResponse<Room>> {
    let params = new HttpParams().set('page', page);
    if (filters.property_id != null) {
      params = params.set('property_id', filters.property_id);
    }
    if (filters.room_type_id != null) {
      params = params.set('room_type_id', filters.room_type_id);
    }
    if (filters.operational_state) {
      params = params.set('operational_state', filters.operational_state);
    }
    return this.http.get<PaginatedResponse<Room>>(`${this.base}/rooms/`, { params });
  }

  get(id: number): Observable<Room> {
    return this.http.get<Room>(`${this.base}/rooms/${id}/`);
  }
}
