import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthService } from './auth.service';

/** Protects every authenticated route. Auth state is established once at
 * app startup (see `app.config.ts`'s initializer, which awaits
 * `GET /api/auth/me/` before the router activates any route), so this guard
 * only needs to read the already-resolved `authenticated` signal — it never
 * re-derives auth from a stale local flag after a refresh. */
export const authGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.authenticated()) {
    return true;
  }
  return router.createUrlTree(['/login']);
};

/** Protects `/login` itself — an already-authenticated user should land in
 * the shell, not see the login form again (and this is what prevents a
 * redirect loop with `authGuard` above: exactly one of the two guards can
 * ever redirect for a given auth state). */
export const guestGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (!authService.authenticated()) {
    return true;
  }
  return router.createUrlTree(['/']);
};
