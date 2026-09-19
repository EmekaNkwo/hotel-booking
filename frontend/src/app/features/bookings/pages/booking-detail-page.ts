import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatTableModule } from '@angular/material/table';

import { BookingStore } from '../store/booking.store';
import { AllocationStore } from '../../allocation/store/allocation.store';
import { HousekeepingStore } from '../../housekeeping/store/housekeeping.store';
import { HousekeepingTask } from '../../housekeeping/models/housekeeping-task.model';
import { BookingLine } from '../models/booking.model';
import { generateIdempotencyKey } from '../../../shared/utils/idempotency-key';

/** `/bookings/:id` — the authoritative Booking, rendered exactly as
 * returned. `guest_snapshot` (captured at confirm time) is shown
 * separately from any current `GuestProfile` — the booking is historical
 * evidence and is never reconciled with live guest data. Room assignment
 * comes straight from each line's own `room_id` (set by
 * `AllocationService.allocate_line()`, M11).
 *
 * Allocation and checkout are both integrated here rather than dedicated
 * pages: A0 exposes no candidate-room endpoint (allocation is one direct
 * command), and checkout is a single command whose only meaningful next
 * step (the created task) already has its own detail page to link to.
 * Neither `AllocationStore` nor `HousekeepingStore` ever mutates
 * `BookingStore` directly — after either command succeeds, the booking is
 * reloaded from the server. */
@Component({
  selector: 'app-booking-detail-page',
  imports: [JsonPipe, RouterLink, MatButtonModule, MatTableModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './booking-detail-page.html',
  styleUrl: './booking-detail-page.scss',
})
export class BookingDetailPage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  protected readonly store = inject(BookingStore);
  protected readonly allocationStore = inject(AllocationStore);
  protected readonly housekeepingStore = inject(HousekeepingStore);

  protected readonly lineColumns = ['room_type_id', 'arrival_date', 'departure_date', 'status', 'room', 'actions'];

  /** One idempotency key per in-flight command per line, reused across
   * retries of that exact command; cleared on success. */
  private readonly allocationKeys = new Map<number, string>();
  private readonly checkoutKeys = new Map<number, string>();

  /** The task created by a successful checkout, keyed by booking_line_id,
   * so the template can link straight to its detail page. */
  protected readonly createdTaskByLine = signal<Record<number, HousekeepingTask>>({});

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    void this.store.loadOne(id);
  }

  isAllocatable(line: BookingLine): boolean {
    return line.status === 'confirmed' && line.room_id === null;
  }

  isCheckoutEligible(line: BookingLine): boolean {
    return line.status === 'checked_in';
  }

  async allocate(line: BookingLine): Promise<void> {
    let key = this.allocationKeys.get(line.id);
    if (!key) {
      key = generateIdempotencyKey();
      this.allocationKeys.set(line.id, key);
    }
    const record = await this.allocationStore.allocate({
      booking_line_id: line.id,
      idempotency_key: key,
    });
    if (record) {
      this.allocationKeys.delete(line.id);
      const booking = this.store.current();
      if (booking) {
        await this.store.loadOne(booking.id);
      }
    }
    // On failure (e.g. 409 — room state changed, already allocated), the
    // per-line error renders inline and the same key is reused on retry;
    // the booking is left exactly as last loaded from the server.
  }

  async checkout(line: BookingLine): Promise<void> {
    let key = this.checkoutKeys.get(line.id);
    if (!key) {
      key = generateIdempotencyKey();
      this.checkoutKeys.set(line.id, key);
    }
    const task = await this.housekeepingStore.checkout({
      booking_line_id: line.id,
      idempotency_key: key,
    });
    if (task) {
      this.checkoutKeys.delete(line.id);
      this.createdTaskByLine.update((m) => ({ ...m, [line.id]: task }));
      const booking = this.store.current();
      if (booking) {
        await this.store.loadOne(booking.id);
      }
    }
    // On failure (e.g. 409 — line not checked_in, already checked out), the
    // per-line error renders inline and the same key is reused on retry.
  }
}
