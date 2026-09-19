import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';

import { EmptyState } from '../../shared/ui/empty-state/empty-state';

/** Route-data-driven placeholder for every feature area that begins in A2+
 * (Reservations, Guests, Availability, Bookings, Rooms, Housekeeping,
 * Notifications, Dashboard). Each route below still gets its own
 * lazy-loaded chunk via `loadComponent` — only the rendered component is
 * shared until each area gets its real implementation. */
@Component({
  selector: 'app-placeholder',
  imports: [EmptyState],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <app-empty-state
      [title]="title()"
      description="This area is planned for a later milestone."
    />
  `,
})
export class Placeholder {
  private readonly route = inject(ActivatedRoute);

  protected readonly title = toSignal(
    this.route.data.pipe(map((data) => (data['title'] as string) ?? 'Coming soon')),
    { initialValue: 'Coming soon' },
  );
}
