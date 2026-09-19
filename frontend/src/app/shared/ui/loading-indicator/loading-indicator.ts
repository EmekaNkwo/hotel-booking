import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { MatProgressBarModule } from '@angular/material/progress-bar';

/** A thin top-of-content progress bar for in-flight requests. Renders
 * nothing when not loading, so it never shifts layout. */
@Component({
  selector: 'app-loading-indicator',
  imports: [MatProgressBarModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (loading()) {
      <mat-progress-bar mode="indeterminate" aria-label="Loading" />
    }
  `,
  styles: `
    :host {
      display: block;
      height: 3px;
    }
  `,
})
export class LoadingIndicator {
  readonly loading = input(false);
}
