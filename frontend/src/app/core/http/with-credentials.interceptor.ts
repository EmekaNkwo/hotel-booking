import { HttpInterceptorFn } from '@angular/common/http';

import { environment } from '../../../environments/environment';

/** The backend uses Django session-cookie auth — every request to the API
 * must carry the session (and CSRF) cookies cross-origin. Centralized here
 * so feature services never need to remember `withCredentials: true`
 * themselves. */
export const withCredentialsInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(environment.apiBaseUrl)) {
    return next(req);
  }
  return next(req.clone({ withCredentials: true }));
};
