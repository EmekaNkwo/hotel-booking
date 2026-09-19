import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { ReservationApiService } from '../../reservations/api/reservation-api.service';
import { BookingApiService } from '../../bookings/api/booking-api.service';
import { RoomApiService } from '../../rooms/api/room-api.service';
import { HousekeepingApiService } from '../../housekeeping/api/housekeeping-api.service';
import { NotificationApiService } from '../../notifications/api/notification-api.service';
import { Reservation } from '../../reservations/models/reservation.model';
import { Booking } from '../../bookings/models/booking.model';
import { Room, RoomOperationalState } from '../../rooms/models/room.model';
import { HousekeepingTask, HousekeepingTaskStatus } from '../../housekeeping/models/housekeeping-task.model';
import { NotificationJob } from '../../notifications/models/notification-job.model';
import { ApiError, fromHttpError } from '../../../shared/models/api-error.model';
import { PaginatedResponse } from '../../../shared/models/paginated-response.model';

/** One independent panel's load state — a failure here never blanks the
 * rest of the dashboard (each panel renders or fails on its own). */
export interface PanelState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
}

function emptyPanel<T>(): PanelState<T> {
  return { data: null, loading: false, error: null };
}

const ROOM_STATES: RoomOperationalState[] = [
  'vacant_clean', 'vacant_dirty', 'occupied_clean', 'occupied_dirty',
  'out_of_service', 'out_of_order', 'cleaning', 'inspected',
];
const TASK_STATES: HousekeepingTaskStatus[] = [
  'planned', 'assigned', 'in_progress', 'quality_check', 'verified', 'defect',
];

function zeroCounts<S extends string>(states: S[]): Record<S, number> {
  return Object.fromEntries(states.map((s) => [s, 0])) as Record<S, number>;
}

/** A read-only composition layer over existing feature APIs — it never
 * mutates reservations/bookings/rooms/housekeeping/notifications, and it
 * owns no business state of its own.
 *
 * R1.1/R1.2: every count here is either the backend's own paginated `count`
 * for a deliberately filtered query, or a sum of such counts — never
 * `results.length`/`.data.length` on a page-1-only array, which would
 * silently under-report once a tenant has more than one page of a given
 * state. `reservations().data`/`bookings().data`/etc. remain page-1-only
 * arrays used solely for bounded preview lists (e.g. "recent bookings",
 * capped at 10) — never for a total. `arrivalsTodayCount` uses the minimal
 * `?arrival_date=` filter added to `BookingListView` for exactly this
 * (R1.2) — filtering the aggregate's own indexed `arrival_date` field, a
 * different (and simpler) semantic than `BookingQuery
 * .arrivals_for_property()`'s line-level "confirmed/checked-in today"
 * selector, which this dashboard widget does not attempt to replicate. */
@Injectable({ providedIn: 'root' })
export class DashboardStore {
  private readonly reservationApi = inject(ReservationApiService);
  private readonly bookingApi = inject(BookingApiService);
  private readonly roomApi = inject(RoomApiService);
  private readonly housekeepingApi = inject(HousekeepingApiService);
  private readonly notificationApi = inject(NotificationApiService);

  readonly reservations = signal<PanelState<Reservation[]>>(emptyPanel());
  readonly bookings = signal<PanelState<Booking[]>>(emptyPanel());
  readonly rooms = signal<PanelState<Room[]>>(emptyPanel());
  readonly housekeepingTasks = signal<PanelState<HousekeepingTask[]>>(emptyPanel());
  readonly problemNotifications = signal<PanelState<NotificationJob[]>>(emptyPanel());

  /** Total room count from the backend's own paginated `count` — NOT
   * `.data.length`, which would only ever reflect page 1. Used by the
   * "View rooms (n)" link; there is no equivalent for housekeeping (no
   * template renders a housekeeping total), so no such signal exists here
   * — R1.2: an earlier `housekeepingTasksCount` signal was computed from
   * every `loadAll()` but never read anywhere; removed rather than kept as
   * unused surface. */
  readonly roomsCount = signal(0);

  /** Per-state counts, each the authoritative `count` of a dedicated
   * `?operational_state=`/`?status=` filtered query — accurate regardless
   * of how many total rows the tenant has, without downloading them. */
  readonly roomStatusCounts = signal<Record<RoomOperationalState, number>>(zeroCounts(ROOM_STATES));
  readonly housekeepingStatusCounts = signal<Record<HousekeepingTaskStatus, number>>(zeroCounts(TASK_STATES));

  readonly occupiedRoomsCount = computed(() => {
    const counts = this.roomStatusCounts();
    return counts.occupied_clean + counts.occupied_dirty;
  });

  /** Sum of the `count` from a `?status=held` and a `?status=awaiting_payment`
   * filtered query — authoritative regardless of total reservation volume. */
  readonly activeReservationsCount = signal(0);

  /** The `count` of a dedicated `?status=confirmed` filtered query. */
  readonly confirmedBookingsCount = signal(0);

  /** The `count` of a dedicated `?arrival_date=<today>` filtered query
   * (R1.2) — authoritative regardless of how many bookings the tenant has,
   * unlike scanning the bounded `bookings()` preview page. */
  readonly arrivalsTodayCount = signal(0);

  readonly recentBookings = computed(() => (this.bookings().data ?? []).slice(0, 10));

  /** Loads every panel independently — one panel's failure is captured on
   * that panel alone and never prevents the others from loading. */
  async loadAll(): Promise<void> {
    await Promise.all([
      this.loadPanel(this.reservations, () => firstValueFrom(this.reservationApi.list())),
      this.loadPanel(this.bookings, () => firstValueFrom(this.bookingApi.list())),
      this.loadPanel(this.rooms, () => firstValueFrom(this.roomApi.list()), this.roomsCount),
      this.loadPanel(this.housekeepingTasks, () => firstValueFrom(this.housekeepingApi.list())),
      this.loadProblemNotifications(),
      this.loadActiveReservationsCount(),
      this.loadConfirmedBookingsCount(),
      this.loadArrivalsTodayCount(),
      this.loadRoomStatusCounts(),
      this.loadHousekeepingStatusCounts(),
    ]);
  }

  private async loadPanel<T>(
    target: ReturnType<typeof signal<PanelState<T[]>>>,
    call: () => Promise<PaginatedResponse<T>>,
    countTarget?: ReturnType<typeof signal<number>>,
  ): Promise<void> {
    target.set({ ...target(), loading: true, error: null });
    try {
      const response = await call();
      target.set({ data: response.results, loading: false, error: null });
      countTarget?.set(response.count);
    } catch (err) {
      target.set({ data: null, loading: false, error: fromHttpError(err) });
    }
  }

  private async loadProblemNotifications(): Promise<void> {
    this.problemNotifications.set({ ...this.problemNotifications(), loading: true, error: null });
    try {
      const [failed, deadLettered] = await Promise.all([
        firstValueFrom(this.notificationApi.list({ status: 'failed' })),
        firstValueFrom(this.notificationApi.list({ status: 'dead_lettered' })),
      ]);
      const combined = [...deadLettered.results, ...failed.results].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      this.problemNotifications.set({ data: combined, loading: false, error: null });
    } catch (err) {
      this.problemNotifications.set({ data: null, loading: false, error: fromHttpError(err) });
    }
  }

  private async loadActiveReservationsCount(): Promise<void> {
    try {
      const [held, awaitingPayment] = await Promise.all([
        firstValueFrom(this.reservationApi.list('held')),
        firstValueFrom(this.reservationApi.list('awaiting_payment')),
      ]);
      this.activeReservationsCount.set(held.count + awaitingPayment.count);
    } catch {
      // Panel-less scalar: a failure here leaves the last-known count in
      // place rather than blanking a widget with no error affordance.
    }
  }

  private async loadConfirmedBookingsCount(): Promise<void> {
    try {
      const confirmed = await firstValueFrom(this.bookingApi.list('confirmed'));
      this.confirmedBookingsCount.set(confirmed.count);
    } catch {
      // See loadActiveReservationsCount().
    }
  }

  private async loadArrivalsTodayCount(): Promise<void> {
    try {
      const today = new Date().toISOString().slice(0, 10);
      const response = await firstValueFrom(this.bookingApi.list(undefined, 1, today));
      this.arrivalsTodayCount.set(response.count);
    } catch {
      // See loadActiveReservationsCount().
    }
  }

  private async loadRoomStatusCounts(): Promise<void> {
    try {
      const responses = await Promise.all(
        ROOM_STATES.map((state) => firstValueFrom(this.roomApi.list({ operational_state: state }))),
      );
      const counts = zeroCounts(ROOM_STATES);
      ROOM_STATES.forEach((state, i) => (counts[state] = responses[i].count));
      this.roomStatusCounts.set(counts);
    } catch {
      // See loadActiveReservationsCount().
    }
  }

  private async loadHousekeepingStatusCounts(): Promise<void> {
    try {
      const responses = await Promise.all(
        TASK_STATES.map((state) => firstValueFrom(this.housekeepingApi.list({ status: state }))),
      );
      const counts = zeroCounts(TASK_STATES);
      TASK_STATES.forEach((state, i) => (counts[state] = responses[i].count));
      this.housekeepingStatusCounts.set(counts);
    } catch {
      // See loadActiveReservationsCount().
    }
  }
}
