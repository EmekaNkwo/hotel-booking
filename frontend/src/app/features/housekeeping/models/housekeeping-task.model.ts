/** The exact M12 task-status enum (apps/housekeeping/models.py). No
 * frontend-only state — render whichever of these six values the backend
 * returns. M12 deliberately did not add priority/due_at/assignment fields
 * beyond `assignee_id`, and did not add a CLEANING → out-of-service route
 * for a failed inspection — neither is invented here. */
export type HousekeepingTaskStatus =
  | 'planned'
  | 'assigned'
  | 'in_progress'
  | 'quality_check'
  | 'verified'
  | 'defect';

/** The exact M12 task-kind enum. M12 only ever produces `departure`. */
export type HousekeepingTaskKind = 'departure' | 'daily' | 'defect' | 'deep_clean';

/** The exact M12 inspection-result enum (apps/housekeeping/models.py). */
export type InspectionResult = 'pass' | 'fail';

/** Matches `HousekeepingTaskSerializer` (apps/housekeeping/api/serializers.py). */
export interface HousekeepingTask {
  id: number;
  room_id: number;
  booking_line_id: number;
  business_date: string;
  task_kind: HousekeepingTaskKind;
  status: HousekeepingTaskStatus;
  assignee_id: number | null;
  created_at: string;
}

/** `GET /api/housekeeping/tasks/`'s optional server-side filters. */
export interface HousekeepingTaskListFilters {
  status?: HousekeepingTaskStatus;
  room_id?: number;
}

export interface CheckoutRequest {
  booking_line_id: number;
  idempotency_key?: string;
}

export interface InspectRequest {
  result: InspectionResult;
  idempotency_key?: string;
}
