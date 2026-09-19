import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatTableModule } from '@angular/material/table';

import { ReservationStore } from '../store/reservation.store';
import { EmptyState } from '../../../shared/ui/empty-state/empty-state';
import { Pagination } from '../../../shared/ui/pagination/pagination';

/** `/reservations` — a basic list using the A2-added
 * `GET /api/reservations/` (see `ReservationListCreateView`'s docstring).
 * No filtering beyond what the endpoint already supports; pagination is
 * server-driven via `store.nextPage()`/`previousPage()` (R1.1). */
@Component({
  selector: 'app-reservation-list-page',
  imports: [RouterLink, DatePipe, MatButtonModule, MatTableModule, EmptyState, Pagination],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './reservation-list-page.html',
  styleUrl: './reservation-list-page.scss',
})
export class ReservationListPage implements OnInit {
  protected readonly store = inject(ReservationStore);
  protected readonly columns = ['reservation_ref', 'status', 'property_id', 'created_at', 'actions'];

  ngOnInit(): void {
    void this.store.loadList();
  }
}
