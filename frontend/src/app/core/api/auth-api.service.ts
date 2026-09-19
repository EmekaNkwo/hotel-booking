import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { CurrentUserResponse, LoginResult } from '../../shared/models/auth.model';

/** Thin HTTP wrapper over `POST /api/auth/login/`, `POST /api/auth/mfa/`,
 * `POST /api/auth/logout/`, `GET /api/auth/me/`. No auth state, no business
 * rules — that belongs in `AuthService`. */
@Injectable({ providedIn: 'root' })
export class AuthApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  login(email: string, password: string): Observable<LoginResult> {
    return this.http.post<LoginResult>(`${this.base}/auth/login/`, { email, password });
  }

  completeMfa(code: string): Observable<LoginResult> {
    return this.http.post<LoginResult>(`${this.base}/auth/mfa/`, { code });
  }

  logout(): Observable<void> {
    return this.http.post<void>(`${this.base}/auth/logout/`, {});
  }

  me(): Observable<CurrentUserResponse> {
    return this.http.get<CurrentUserResponse>(`${this.base}/auth/me/`);
  }
}
