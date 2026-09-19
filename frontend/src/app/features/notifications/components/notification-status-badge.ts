import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { NotificationJobStatus } from '../models/notification-job.model';

/** Consistent visual treatment for the five M13 job states — same
 * severity-grouped pattern as A4's `RoomStatusBadge`/A5's
 * `HousekeepingStatusBadge`. */
@Component({
  selector: 'app-notification-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="notif-status" [class]="severityClass()">{{ status() }}</span>`,
  styles: `
    .notif-status {
      display: inline-block;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.02em;
      padding: 0.15rem 0.6rem;
      border-radius: 4px;
      font-size: 0.85rem;
    }
    .severity-ok {
      background-color: var(--mat-sys-tertiary-container);
      color: var(--mat-sys-on-tertiary-container);
    }
    .severity-attention {
      background-color: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container);
    }
    .severity-blocked {
      background-color: var(--mat-sys-error-container);
      color: var(--mat-sys-on-error-container);
    }
  `,
})
export class NotificationStatusBadge {
  readonly status = input.required<NotificationJobStatus>();

  protected readonly severityClass = computed(() => {
    switch (this.status()) {
      case 'delivered':
        return 'severity-ok';
      case 'pending':
      case 'delivering':
        return 'severity-attention';
      case 'failed':
      case 'dead_lettered':
        return 'severity-blocked';
    }
  });
}
