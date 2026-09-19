/** Matches `PropertySerializer` (apps/properties/api/serializers.py, A2). */
export interface Property {
  id: number;
  code: string;
  name: string;
  status: string;
  currency: string;
  timezone: string;
}
