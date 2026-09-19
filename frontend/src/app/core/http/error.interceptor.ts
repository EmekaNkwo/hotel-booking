import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { AuthService } from '../auth/auth.service';
import { TenantService } from '../tenant/tenant.service';
import { ToastService } from '../../shared/ui/toast/toast.service';
import { ApiError, toApiError } from '../../shared/models/api-error.model';
import { environment } from '../../../environments/environment';

/** Requests whose own 401 is a normal, inline-handled outcome (wrong
 * password, invalid/expired MFA code) — never a session-expiry redirect. */
const AUTH_ATTEMPT_PATHS = ['/auth/login/', '/auth/mfa/'];

/** Extends the thrown error with a normalized `apiError` so any caller can
 * read a ready-made message without re-parsing the response body — while
 * `error`/`status` (the original `HttpErrorResponse` shape) stay intact for
 * callers that want the raw body themselves (e.g. field-level 400s). */
export interface NormalizedHttpError extends HttpErrorResponse {
  apiError: ApiError;
}

/** Global HTTP error handling: normalizes every error, redirects on real
 * session expiry (never on a login/MFA attempt's own 401), and surfaces
 * infrastructure-level failures (network/5xx/429) as a toast since no
 * component is positioned to render those usefully. Business errors
 * (400/403/404/409) are left for the calling component to render — this
 * interceptor never replaces a useful backend message with a generic one. */
export const errorInterceptor: HttpInterceptorFn = (req, next) => {
  const router = inject(Router);
  const authService = inject(AuthService);
  const tenantService = inject(TenantService);
  const toast = inject(ToastService);

  return next(req).pipe(
    catchError((error: unknown) => {
      if (!(error instanceof HttpErrorResponse) || !req.url.startsWith(environment.apiBaseUrl)) {
        return throwError(() => error);
      }

      const apiError = toApiError(error.status, error.error);
      const normalized: NormalizedHttpError = Object.assign(error, { apiError });

      const isAuthAttempt = AUTH_ATTEMPT_PATHS.some((path) => req.url.includes(path));
      if (error.status === 401 && !isAuthAttempt) {
        const wasAuthenticated = authService.authenticated();
        authService.clearLocalState();
        tenantService.clear();
        if (wasAuthenticated && !router.url.startsWith('/login')) {
          toast.info('Your session has expired. Please log in again.');
        }
        if (!router.url.startsWith('/login')) {
          void router.navigate(['/login']);
        }
      } else if (error.status === 0 || error.status >= 500 || error.status === 429) {
        toast.error(apiError.message);
      }

      return throwError(() => normalized);
    }),
  );
};
