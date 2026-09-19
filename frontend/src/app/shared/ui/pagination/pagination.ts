import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';

/** R1.1: the shared pager control for every paginated list screen —
 * Previous/Next only (no jump-to-page), driven entirely by the backend's
 * own `next`/`previous` presence (never a locally-computed page count, and
 * never a hardcoded PAGE_SIZE) so it can never desync from what the server
 * actually has. `count` is shown for orientation only. */
@Component({
  selector: 'app-pagination',
  imports: [MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="pagination">
      <span class="pagination-summary">{{ count() }} total</span>
      <span class="pagination-page">Page {{ page() }}</span>
      <button
        mat-button
        type="button"
        [disabled]="!hasPrevious()"
        (click)="previous.emit()"
      >
        Previous
      </button>
      <button mat-button type="button" [disabled]="!hasNext()" (click)="next.emit()">
        Next
      </button>
    </div>
  `,
  styles: `
    .pagination {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0.5rem 0;
      font-size: 0.9rem;
      color: var(--mat-sys-on-surface-variant);
    }
  `,
})
export class Pagination {
  readonly count = input.required<number>();
  readonly page = input.required<number>();
  readonly hasNext = input.required<boolean>();
  readonly hasPrevious = input.required<boolean>();

  readonly next = output<void>();
  readonly previous = output<void>();
}
