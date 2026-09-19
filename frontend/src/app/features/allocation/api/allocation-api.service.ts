import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../environments/environment';
import { AllocateLineRequest, AllocationRecord } from '../models/allocation-record.model';

/** Thin wrapper over the Allocation HTTP surface (apps/allocation/api, A0).
 * `AllocationService.allocate_line()` is the ONLY entry point — there is no
 * candidate-list endpoint, so this service exposes exactly the direct
 * "allocate" command the backend supports, nothing invented. No
 * scoring/selection logic lives here. */
@Injectable({ providedIn: 'root' })
export class AllocationApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  allocate(request: AllocateLineRequest): Observable<AllocationRecord> {
    return this.http.post<AllocationRecord>(`${this.base}/allocation/allocate/`, request);
  }
}
