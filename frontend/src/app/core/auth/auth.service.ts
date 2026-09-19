import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AuthApiService } from '../api/auth-api.service';
import { isMfaChallenge } from '../../shared/models/auth.model';
import { Membership } from '../../shared/models/membership.model';
import { User } from '../../shared/models/user.model';
import { ApiError, fromHttpError } from '../../shared/models/api-error.model';

/** Outcome of a login attempt the login screen renders directly. */
export type LoginOutcome =
  | { kind: 'authenticated' }
  | { kind: 'mfa_required' }
  | { kind: 'error'; error: ApiError };

/** Application-wide authentication state and behavior (signals only — no
 * NgRx, no client-side copy of business state). The backend session cookie
 * is the actual authentication mechanism; this service just reflects it. */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(AuthApiService);

  readonly currentUser = signal<User | null>(null);
  readonly memberships = signal<Membership[]>([]);
  readonly authenticated = computed(() => this.currentUser() !== null);
  readonly loading = signal(false);
  readonly error = signal<ApiError | null>(null);
  /** True between a successful password step and a successful/failed MFA
   * code submission — drives the login screen's second step. */
  readonly mfaPending = signal(false);

  /** Called once on app startup (see `app.config.ts`'s initializer) to
   * establish auth state from the session cookie — never trust a stale
   * client-side signal across a page refresh. */
  async loadCurrentUser(): Promise<void> {
    this.loading.set(true);
    try {
      const response = await firstValueFrom(this.api.me());
      this.currentUser.set(response.user);
      this.memberships.set(response.memberships);
    } catch {
      this.currentUser.set(null);
      this.memberships.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  async login(email: string, password: string): Promise<LoginOutcome> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const result = await firstValueFrom(this.api.login(email, password));
      if (isMfaChallenge(result)) {
        this.mfaPending.set(true);
        return { kind: 'mfa_required' };
      }
      this.mfaPending.set(false);
      this.currentUser.set(result.user);
      this.memberships.set(result.memberships);
      return { kind: 'authenticated' };
    } catch (err) {
      const apiError = fromHttpError(err);
      this.error.set(apiError);
      return { kind: 'error', error: apiError };
    } finally {
      this.loading.set(false);
    }
  }

  async completeMfa(code: string): Promise<LoginOutcome> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const result = await firstValueFrom(this.api.completeMfa(code));
      if (isMfaChallenge(result)) {
        // The backend contract never actually returns this from /auth/mfa/,
        // but the union type is shared with login() — treat defensively.
        return { kind: 'mfa_required' };
      }
      this.mfaPending.set(false);
      this.currentUser.set(result.user);
      this.memberships.set(result.memberships);
      return { kind: 'authenticated' };
    } catch (err) {
      const apiError = fromHttpError(err);
      this.error.set(apiError);
      return { kind: 'error', error: apiError };
    } finally {
      this.loading.set(false);
    }
  }

  async logout(): Promise<void> {
    try {
      await firstValueFrom(this.api.logout());
    } finally {
      this.clearLocalState();
    }
  }

  /** Called by the error interceptor when a 401 arrives on an
   * already-authenticated session (expired/invalidated server-side). */
  clearLocalState(): void {
    this.currentUser.set(null);
    this.memberships.set([]);
    this.mfaPending.set(false);
    this.error.set(null);
  }
}

