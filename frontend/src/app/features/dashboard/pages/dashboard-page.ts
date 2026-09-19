import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';

import { DashboardStore } from '../store/dashboard.store';
import { NotificationStatusBadge } from '../../notifications/components/notification-status-badge';

/** `/dashboard` — the default route. Composes existing feature APIs
 * (Reservations, Bookings, Rooms, Housekeeping, Notifications) read-only
 * through `DashboardStore`; it owns no business state and performs no
 * mutation. Each panel loads and fails independently. */
@Component({
  selector: 'app-dashboard-page',
  imports: [RouterLink, MatButtonModule, NotificationStatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './dashboard-page.html',
  styleUrl: './dashboard-page.scss',
})
export class DashboardPage implements OnInit {
  protected readonly store = inject(DashboardStore);

  ngOnInit(): void {
    void this.store.loadAll();
  }

  refresh(): void {
    void this.store.loadAll();
  }
}
