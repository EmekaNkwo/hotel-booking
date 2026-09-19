import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';

import { RoomStore } from '../store/room.store';
import { RoomStatusBadge } from '../components/room-status-badge';
import { RoomOperationalState } from '../models/room.model';
import { EmptyState } from '../../../shared/ui/empty-state/empty-state';
import { Pagination } from '../../../shared/ui/pagination/pagination';

const OPERATIONAL_STATES: RoomOperationalState[] = [
  'vacant_clean', 'vacant_dirty', 'occupied_clean', 'occupied_dirty',
  'out_of_service', 'out_of_order', 'cleaning', 'inspected',
];

/** `/rooms` — the operational room board. Filtering is entirely
 * server-side (`?property_id=`, `?room_type_id=`, `?operational_state=`,
 * apps/rooms/api) — every filter change re-issues the list request rather
 * than filtering a downloaded dataset in the browser. */
@Component({
  selector: 'app-room-list-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatSelectModule,
    MatTableModule,
    RoomStatusBadge,
    EmptyState,
    Pagination,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './room-list-page.html',
  styleUrl: './room-list-page.scss',
})
export class RoomListPage implements OnInit {
  private readonly fb = inject(FormBuilder);
  protected readonly store = inject(RoomStore);
  protected readonly operationalStates = OPERATIONAL_STATES;
  protected readonly columns = ['code', 'room_type', 'operational_state', 'assignment', 'actions'];

  protected readonly filterForm = this.fb.nonNullable.group({
    property_id: [null as number | null],
    room_type_id: [null as number | null],
    operational_state: [null as RoomOperationalState | null],
  });

  private readonly filterValue = toSignal(this.filterForm.valueChanges, {
    initialValue: this.filterForm.getRawValue(),
  });

  ngOnInit(): void {
    void this.store.loadReferenceData();
    void this.store.loadList();
  }

  applyFilters(): void {
    const v = this.filterForm.getRawValue();
    void this.store.loadList({
      property_id: v.property_id ?? undefined,
      room_type_id: v.room_type_id ?? undefined,
      operational_state: v.operational_state ?? undefined,
    });
  }

  clearFilters(): void {
    this.filterForm.reset({ property_id: null, room_type_id: null, operational_state: null });
    void this.store.loadList({});
  }

  protected readonly hasActiveFilters = computed(() => {
    const v = this.filterValue();
    return !!(v.property_id || v.room_type_id || v.operational_state);
  });
}
