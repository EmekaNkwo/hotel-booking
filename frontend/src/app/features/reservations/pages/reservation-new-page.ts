import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';

import { ReservationStore } from '../store/reservation.store';
import { GuestSearch } from '../../guests/components/guest-search';
import { GuestProfile } from '../../guests/models/guest.model';
import { generateIdempotencyKey } from '../../../shared/utils/idempotency-key';

interface IncomingSelection {
  property_id: number;
  room_type_id: number;
  start: string;
  end: string;
  quantity: number;
  adults: number;
  children: number;
}

function isIncomingSelection(value: unknown): value is IncomingSelection {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const v = value as Record<string, unknown>;
  return (
    typeof v['property_id'] === 'number' &&
    typeof v['room_type_id'] === 'number' &&
    typeof v['start'] === 'string' &&
    typeof v['end'] === 'string'
  );
}

/** `/reservations/new` — a focused single-page flow, not a wizard: the
 * stay is already chosen (carried from `/availability`'s "Start
 * reservation" action via router state), so this page's only job is guest
 * identification + submitting `POST /api/reservations/`. */
@Component({
  selector: 'app-reservation-new-page',
  imports: [RouterLink, MatButtonModule, GuestSearch],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './reservation-new-page.html',
  styleUrl: './reservation-new-page.scss',
})
export class ReservationNewPage implements OnInit {
  protected readonly store = inject(ReservationStore);
  private readonly router = inject(Router);

  protected readonly selection = signal<IncomingSelection | null>(null);
  protected readonly selectedGuest = signal<GuestProfile | null>(null);

  /** Generated ONCE per command (this page instance) — reused verbatim if
   * the user retries the same submission, never regenerated per attempt. */
  private readonly idempotencyKey = generateIdempotencyKey();

  ngOnInit(): void {
    const state = this.router.getCurrentNavigation()?.extras.state ?? window.history.state;
    if (isIncomingSelection(state)) {
      this.selection.set(state);
    }
  }

  onGuestSelected(guest: GuestProfile): void {
    this.selectedGuest.set(guest);
  }

  async submit(): Promise<void> {
    const selection = this.selection();
    const guest = this.selectedGuest();
    if (!selection || !guest) {
      return;
    }
    const reservation = await this.store.create({
      property_id: selection.property_id,
      guest_email: guest.primary_email,
      guest_phone: guest.primary_phone,
      lines: [
        {
          room_type_id: selection.room_type_id,
          arrival_date: selection.start,
          departure_date: selection.end,
          adults: selection.adults,
          children: selection.children,
          quantity: selection.quantity,
        },
      ],
      idempotency_key: this.idempotencyKey,
    });
    if (reservation) {
      await this.router.navigate(['/reservations', reservation.id]);
    }
    // On failure, `store.error()` renders the backend's message in the
    // template — the same idempotency key is reused if the user retries.
  }
}
