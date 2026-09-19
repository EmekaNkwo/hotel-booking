import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { TenantMembership } from '../../shared/models/tenant.model';

/** Thin HTTP wrapper over `GET /api/tenants/` — the cross-tenant read that
 * deliberately works without a resolved tenant context. */
@Injectable({ providedIn: 'root' })
export class TenantApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(): Observable<TenantMembership[]> {
    return this.http.get<TenantMembership[]>(`${this.base}/tenants/`);
  }
}
