import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { TenantService } from '../tenant/tenant.service';
import { environment } from '../../../environments/environment';

/** Attaches `X-Tenant-Id` to every tenant-scoped API request automatically —
 * feature services never attach this header themselves (per A1 spec §5).
 * Harmless to send on the few endpoints that ignore it (`/auth/*`,
 * `/tenants/`): the middleware only consults the header when a tenant
 * context decision is actually being made. */
export const tenantInterceptor: HttpInterceptorFn = (req, next) => {
  if (!req.url.startsWith(environment.apiBaseUrl)) {
    return next(req);
  }

  const tenantId = inject(TenantService).selectedTenantId();
  if (tenantId === null) {
    return next(req);
  }

  return next(req.clone({ setHeaders: { 'X-Tenant-Id': String(tenantId) } }));
};
