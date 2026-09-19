/** The exact M13 job-status enum (apps/notifications/models.py). No
 * frontend-only state — render whichever of these five values the backend
 * returns. */
export type NotificationJobStatus = 'pending' | 'delivering' | 'delivered' | 'failed' | 'dead_lettered';

/** Matches `NotificationJobSerializer` (apps/notifications/api/serializers.py).
 * Read-only — M13 exposes no staff-triggerable mutation (delivery is
 * Celery/projector-driven), and no `DeliveryAttempt`/retry/requeue
 * endpoint exists, so neither is represented here. */
export interface NotificationJob {
  id: number;
  notification_type: string;
  channel: string;
  status: NotificationJobStatus;
  retry_count: number;
  last_error: string;
  recipient_guest_id: number | null;
  context: Record<string, unknown>;
  created_at: string;
}

/** `GET /api/notifications/`'s optional server-side filter. */
export interface NotificationJobListFilters {
  status?: NotificationJobStatus;
}
