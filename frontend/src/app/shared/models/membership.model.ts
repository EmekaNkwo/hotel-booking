/** Matches `MembershipSerializer` (apps/accounts/api/serializers.py). */
export interface Membership {
  id: number;
  tenant_id: number;
  email: string;
  status: string;
  role_names: string[];
}
