import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { RoomOperationalState } from '../models/room.model';

/** Consistent visual treatment for the eight M3 operational states —
 * mirrors the reservation/booking status badge pattern from A2/A3, with a
 * severity class layered on since these eight states genuinely group into
 * good/attention/blocked, unlike the simpler linear reservation lifecycle. */
@Component({
  selector: 'app-room-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="room-status" [class]="severityClass()">{{ state() }}</span>`,
  styles: `
    .room-status {
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
export class RoomStatusBadge {
  readonly state = input.required<RoomOperationalState>();

  protected readonly severityClass = computed(() => {
    switch (this.state()) {
      case 'vacant_clean':
        return 'severity-ok';
      case 'vacant_dirty':
      case 'occupied_dirty':
        return 'severity-attention';
      case 'out_of_service':
      case 'out_of_order':
        return 'severity-blocked';
      case 'occupied_clean':
      case 'cleaning':
      case 'inspected':
        return 'severity-neutral';
    }
  });
}
