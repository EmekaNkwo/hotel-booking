/** Matches `UserAccountSerializer` (apps/accounts/api/serializers.py). */
export interface User {
  id: number;
  email: string;
  is_staff: boolean;
  is_active: boolean;
}
