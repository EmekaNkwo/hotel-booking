import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { Property } from '../models/property.model';

/** Thin wrapper over `GET /api/properties/` (A2 addition to A0's surface —
 * see apps/properties/api's module docstring for why it exists). */
@Injectable({ providedIn: 'root' })
export class PropertyApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(): Observable<Property[]> {
    return this.http.get<Property[]>(`${this.base}/properties/`);
  }
}
