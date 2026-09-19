import { Membership } from './membership.model';
import { User } from './user.model';

/** `POST /api/auth/login/` and `POST /api/auth/mfa/` share this 200 shape. */
export interface AuthSession {
  user: User;
  memberships: Membership[];
}

/** `POST /api/auth/login/` returns this 202 shape when the account's role
 * requires MFA (SDD §14.1) — the password was correct but the session is
 * not yet authenticated until the code step completes. */
export interface MfaChallengeRequired {
  requires_mfa: true;
  expires_in: number;
}

export type LoginResult = AuthSession | MfaChallengeRequired;

export function isMfaChallenge(result: LoginResult): result is MfaChallengeRequired {
  return (result as MfaChallengeRequired).requires_mfa === true;
}

/** `GET /api/auth/me/` — the resolved tenant is null until a tenant is
 * selected (single membership auto-resolves server-side; multiple does not). */
export interface CurrentUserResponse {
  user: User;
  memberships: Membership[];
  tenant_id: number | null;
}
