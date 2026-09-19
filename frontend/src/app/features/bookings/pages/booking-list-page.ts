import { CurrencyPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatTableModule } from '@angular/material/table';

import { BookingStore } from '../store/booking.store';
import { EmptyState } from '../../../shared/ui/empty-state/empty-state';
import { Pagination } from '../../../shared/ui/pagination/pagination';

/** `/bookings` — a dense operational list using the real
 * `GET /api/bookings/` (apps/bookings/api, A0). No client-side filtering
 * over an unbounded dataset — only the `?status=` the backend supports;
 * pagination is server-driven via `store.nextPage()`/`previousPage()` (R1.1). */
@Component({
  selector: 'app-booking-list-page',
  imports: [RouterLink, CurrencyPipe, MatTableModule, EmptyState, Pagination],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './booking-list-page.html',
  styleUrl: './booking-list-page.scss',
})
export class BookingListPage implements OnInit {
  protected readonly store = inject(BookingStore);
  protected readonly columns = [
    'booking_ref',
    'aggregate_status',
    'arrival_date',
    'departure_date',
    'total',
    'lines',
    'actions',
  ];

  ngOnInit(): void {
    void this.store.loadList();
  }
}
