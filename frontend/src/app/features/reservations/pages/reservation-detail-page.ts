import { DecimalPipe, JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatTableModule } from '@angular/material/table';

import { ReservationStore } from '../store/reservation.store';
import { BookingStore } from '../../bookings/store/booking.store';
import { generateIdempotencyKey } from '../../../shared/utils/idempotency-key';

const TERMINAL_STATUSES = new Set(['converted', 'expired', 'cancelled']);

/** `/reservations/:id` — the authoritative reservation, rendered exactly as
 * the backend returns it. Actions (request-payment, cancel, confirm
 * booking) always refetch/replace state from the server response; nothing
 * here sets a status locally. Confirming delegates to `BookingStore` — this
 * page owns no booking business logic of its own. */
@Component({
  selector: 'app-reservation-detail-page',
  imports: [DecimalPipe, JsonPipe, MatButtonModule, MatTableModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './reservation-detail-page.html',
  styleUrl: './reservation-detail-page.scss',
})
export class ReservationDetailPage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  protected readonly store = inject(ReservationStore);
  protected readonly bookingStore = inject(BookingStore);

  protected readonly lineColumns = ['room_type_id', 'arrival_date', 'departure_date', 'quantity', 'total'];

  protected readonly actionsDisabled = computed(() => {
    const reservation = this.store.current();
    return !reservation || TERMINAL_STATUSES.has(reservation.status) || this.store.loading();
  });

  protected readonly confirmDisabled = computed(() => {
    const reservation = this.store.current();
    return !reservation || reservation.status !== 'awaiting_payment' || this.bookingStore.loading();
  });

  /** Reused across retries of the SAME cancel command; cleared once the
   * command resolves (success, or the user navigates to a fresh attempt). */
  private cancelKey: string | null = null;
  /** Same discipline for the confirm-booking command. */
  private confirmKey: string | null = null;

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    void this.store.loadOne(id);
  }

  async requestPayment(): Promise<void> {
    const reservation = this.store.current();
    if (!reservation) {
      return;
    }
    await this.store.requestPayment(reservation.id);
  }

  async cancel(): Promise<void> {
    const reservation = this.store.current();
    if (!reservation) {
      return;
    }
    this.cancelKey ??= generateIdempotencyKey();
    const succeeded = await this.store.cancel(reservation.id, this.cancelKey);
    if (succeeded) {
      this.cancelKey = null;
    }
  }

  async confirmBooking(): Promise<void> {
    const reservation = this.store.current();
    if (!reservation) {
      return;
    }
    this.confirmKey ??= generateIdempotencyKey();
    const booking = await this.bookingStore.confirm({
      reservation_id: reservation.id,
      idempotency_key: this.confirmKey,
    });
    if (booking) {
      this.confirmKey = null;
      await this.router.navigate(['/bookings', booking.id]);
    }
    // On failure (e.g. 409 — already confirmed elsewhere, or no longer
    // eligible), bookingStore.error() renders the backend's message and the
    // same confirmKey is reused if the user retries; we do NOT navigate and
    // never assume a booking now exists.
  }

  refresh(): void {
    const reservation = this.store.current();
    if (reservation) {
      void this.store.loadOne(reservation.id);
    }
  }
}
