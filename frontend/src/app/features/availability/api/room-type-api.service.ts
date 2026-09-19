import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { RoomType } from '../models/room-type.model';

/** Thin wrapper over `GET /api/room-types/` (apps/rooms/api, A0). */
@Injectable({ providedIn: 'root' })
export class RoomTypeApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(): Observable<RoomType[]> {
    return this.http.get<RoomType[]>(`${this.base}/room-types/`);
  }
}
