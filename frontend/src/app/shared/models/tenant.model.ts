/** Matches `TenantMembershipView`'s response (apps/accounts/api/views.py) —
 * one row per active membership, returned by `GET /api/tenants/`. */
export interface TenantMembership {
  tenant_id: number;
  code: string;
  name: string;
  tenant_status: string;
  membership_status: string;
  role_names: string[];
}
