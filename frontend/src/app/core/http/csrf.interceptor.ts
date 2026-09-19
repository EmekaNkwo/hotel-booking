import { HttpInterceptorFn } from '@angular/common/http';

import { readCookie } from './cookie.util';
import { environment } from '../../../environments/environment';

/** Django's default CSRF cookie/header contract (unmodified by A0 — see
 * `config/settings/base.py`'s `CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"`, which
 * Django maps to the `X-CSRFToken` request header): the `csrftoken` cookie's
 * value is echoed back as `X-CSRFToken` on every unsafe request. CSRF is
 * never disabled — this interceptor is the only mechanism used. */
const CSRF_COOKIE_NAME = 'csrftoken';
const CSRF_HEADER_NAME = 'X-CSRFToken';
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

export const csrfInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(environment.apiBaseUrl) || SAFE_METHODS.has(req.method)) {
    return next(req);
  }

  const token = readCookie(CSRF_COOKIE_NAME);
  if (!token) {
    return next(req);
  }

  return next(req.clone({ setHeaders: { [CSRF_HEADER_NAME]: token } }));
};
