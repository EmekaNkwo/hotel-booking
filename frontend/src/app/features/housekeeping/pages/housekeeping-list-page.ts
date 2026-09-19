import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';

import { HousekeepingStore } from '../store/housekeeping.store';
import { HousekeepingStatusBadge } from '../components/housekeeping-status-badge';
import { HousekeepingTaskStatus } from '../models/housekeeping-task.model';
import { EmptyState } from '../../../shared/ui/empty-state/empty-state';
import { Pagination } from '../../../shared/ui/pagination/pagination';

const TASK_STATUSES: HousekeepingTaskStatus[] = [
  'planned', 'assigned', 'in_progress', 'quality_check', 'verified', 'defect',
];

/** `/housekeeping` — the task board. Filtering is entirely server-side
 * (`?status=`, `?room_id=`, apps/housekeeping/api) — no client-side
 * business filtering over an unbounded dataset, and no priority/due-date
 * fields (M12 deliberately does not have them). */
@Component({
  selector: 'app-housekeeping-list-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatTableModule,
    HousekeepingStatusBadge,
    EmptyState,
    Pagination,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './housekeeping-list-page.html',
  styleUrl: './housekeeping-list-page.scss',
})
export class HousekeepingListPage implements OnInit {
  private readonly fb = inject(FormBuilder);
  protected readonly store = inject(HousekeepingStore);
  protected readonly taskStatuses = TASK_STATUSES;
  protected readonly columns = ['id', 'room_id', 'task_kind', 'status', 'business_date', 'actions'];

  protected readonly filterForm = this.fb.nonNullable.group({
    status: [null as HousekeepingTaskStatus | null],
    room_id: [null as number | null],
  });

  private readonly filterValue = toSignal(this.filterForm.valueChanges, {
    initialValue: this.filterForm.getRawValue(),
  });

  protected readonly hasActiveFilters = computed(() => {
    const v = this.filterValue();
    return !!(v.status || v.room_id);
  });

  ngOnInit(): void {
    void this.store.loadList();
  }

  applyFilters(): void {
    const v = this.filterForm.getRawValue();
    void this.store.loadList({
      status: v.status ?? undefined,
      room_id: v.room_id ?? undefined,
    });
  }

  clearFilters(): void {
    this.filterForm.reset({ status: null, room_id: null });
    void this.store.loadList({});
  }
}
