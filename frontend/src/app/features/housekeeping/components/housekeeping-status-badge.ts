import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { HousekeepingTaskStatus } from '../models/housekeeping-task.model';

/** Consistent visual treatment for the six M12 task states — same
 * severity-grouped pattern as A4's `RoomStatusBadge`. */
@Component({
  selector: 'app-housekeeping-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="hk-status" [class]="severityClass()">{{ status() }}</span>`,
  styles: `
    .hk-status {
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
    .severity-neutral {
      background-color: var(--mat-sys-surface-container-high);
      color: var(--mat-sys-on-surface);
    }
  `,
})
export class HousekeepingStatusBadge {
  readonly status = input.required<HousekeepingTaskStatus>();

  protected readonly severityClass = computed(() => {
    switch (this.status()) {
      case 'verified':
        return 'severity-ok';
      case 'in_progress':
      case 'quality_check':
        return 'severity-attention';
      case 'defect':
        return 'severity-blocked';
      case 'planned':
      case 'assigned':
        return 'severity-neutral';
    }
  });
}
