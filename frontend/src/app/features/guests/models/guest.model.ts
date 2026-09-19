/** `name` is `GuestName.to_dict()` (apps/shared/value_objects/guest_name.py)
 * — `{}` when the guest was resolved with no name at all. */
export interface GuestName {
  given_name: string;
  family_name: string;
  display_name: string;
}

/** Matches `GuestProfileSerializer` (apps/guests/api/serializers.py). */
export interface GuestProfile {
  id: number;
  primary_email: string | null;
  primary_phone: string | null;
  name: GuestName | Record<string, never>;
  language: string;
  status: string;
  created_at: string;
}

/** Matches `GuestCreateSerializer`'s input shape (find-or-create by
 * identity — `GuestService.resolve()`, never a raw create). */
export interface GuestResolveRequest {
  email?: string | null;
  phone?: string | null;
  given_name?: string;
  family_name?: string;
  language?: string;
}
