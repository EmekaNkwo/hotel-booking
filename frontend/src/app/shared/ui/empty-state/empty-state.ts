import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** A restrained placeholder surface — used for not-yet-built feature areas
 * (A2+) and genuinely empty lists alike. */
@Component({
  selector: 'app-empty-state',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="empty-state">
      <h2>{{ title() }}</h2>
      @if (description()) {
        <p>{{ description() }}</p>
      }
    </div>
  `,
  styles: `
    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 0.5rem;
      padding: 3rem 1rem;
      color: var(--mat-sys-on-surface-variant);
    }

    h2 {
      margin: 0;
      font: var(--mat-sys-title-medium);
      color: var(--mat-sys-on-surface);
    }

    p {
      margin: 0;
      font: var(--mat-sys-body-medium);
      max-width: 40ch;
    }
  `,
})
export class EmptyState {
  readonly title = input.required<string>();
  readonly description = input<string>('');
}
