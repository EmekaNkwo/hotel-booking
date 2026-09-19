import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
  provideZonelessChangeDetection,
} from '@angular/core';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { AuthService } from './core/auth/auth.service';
import { TenantService } from './core/tenant/tenant.service';
import { csrfInterceptor } from './core/http/csrf.interceptor';
import { errorInterceptor } from './core/http/error.interceptor';
import { tenantInterceptor } from './core/http/tenant.interceptor';
import { withCredentialsInterceptor } from './core/http/with-credentials.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes),
    provideAnimationsAsync(),
    provideHttpClient(
      withInterceptors([
        withCredentialsInterceptor,
        csrfInterceptor,
        tenantInterceptor,
        errorInterceptor,
      ]),
    ),
    // Establish auth state from the session cookie BEFORE the router
    // activates any route — refreshing the page must never show a flash of
    // the login screen (or the shell) based on a stale client-side guess.
    // Both services are injected synchronously, before the first `await` —
    // `inject()` only works within the synchronous injection context the
    // initializer is invoked in; calling it after an `await` (from a
    // resumed microtask) throws NG0203.
    provideAppInitializer(async () => {
      const authService = inject(AuthService);
      const tenantService = inject(TenantService);
      await authService.loadCurrentUser();
      if (authService.authenticated()) {
        await tenantService.loadTenants();
      }
    }),
  ],
};
