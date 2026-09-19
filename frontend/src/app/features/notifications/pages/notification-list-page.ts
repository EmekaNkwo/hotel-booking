import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';

import { NotificationStore } from '../store/notification.store';
import { NotificationStatusBadge } from '../components/notification-status-badge';
import { NotificationJobStatus } from '../models/notification-job.model';
import { EmptyState } from '../../../shared/ui/empty-state/empty-state';
import { Pagination } from '../../../shared/ui/pagination/pagination';

const JOB_STATUSES: NotificationJobStatus[] = [
  'pending', 'delivering', 'delivered', 'failed', 'dead_lettered',
];

/** `/notifications` — staff visibility into delivery/DLQ status. Filtering
 * is entirely server-side (`?status=`, apps/notifications/api) — no
 * client-side business filtering over an unbounded history, and no
 * fabricated retry/requeue action (A0 exposes none). */
@Component({
  selector: 'app-notification-list-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    DatePipe,
    MatButtonModule,
    MatFormFieldModule,
    MatSelectModule,
    MatTableModule,
    NotificationStatusBadge,
    EmptyState,
    Pagination,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './notification-list-page.html',
  styleUrl: './notification-list-page.scss',
})
export class NotificationListPage implements OnInit {
  private readonly fb = inject(FormBuilder);
  protected readonly store = inject(NotificationStore);
  protected readonly jobStatuses = JOB_STATUSES;
  protected readonly columns = ['id', 'notification_type', 'channel', 'status', 'retry_count', 'created_at', 'actions'];

  protected readonly filterForm = this.fb.nonNullable.group({
    status: [null as NotificationJobStatus | null],
  });

  private readonly filterValue = toSignal(this.filterForm.valueChanges, {
    initialValue: this.filterForm.getRawValue(),
  });

  protected readonly hasActiveFilters = computed(() => !!this.filterValue().status);

  ngOnInit(): void {
    void this.store.loadList();
  }

  applyFilters(): void {
    const v = this.filterForm.getRawValue();
    void this.store.loadList({ status: v.status ?? undefined });
  }

  clearFilters(): void {
    this.filterForm.reset({ status: null });
    void this.store.loadList({});
  }
}
