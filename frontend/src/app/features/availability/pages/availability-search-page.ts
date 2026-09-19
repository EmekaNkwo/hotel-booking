import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { provideNativeDateAdapter } from '@angular/material/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { Router } from '@angular/router';

import { AvailabilityStore } from '../store/availability.store';
import { AvailabilityResultsTable } from '../components/availability-results-table';

function toIsoDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** `/availability` — the primary A2 workflow entry point: search real
 * backend availability + pricing for a property/room-type/date-range. */
@Component({
  selector: 'app-availability-search-page',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDatepickerModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    AvailabilityResultsTable,
  ],
  providers: [provideNativeDateAdapter()],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './availability-search-page.html',
  styleUrl: './availability-search-page.scss',
})
export class AvailabilitySearchPage implements OnInit {
  private readonly fb = inject(FormBuilder);
  protected readonly store = inject(AvailabilityStore);
  private readonly router = inject(Router);

  protected readonly form = this.fb.nonNullable.group({
    property_id: [null as number | null, Validators.required],
    room_type_id: [null as number | null, Validators.required],
    start: [null as Date | null, Validators.required],
    end: [null as Date | null, Validators.required],
    quantity: [1, [Validators.required, Validators.min(1)]],
    adults: [1, [Validators.required, Validators.min(1)]],
    children: [0, [Validators.required, Validators.min(0)]],
  });

  private readonly formValue = toSignal(this.form.valueChanges, {
    initialValue: this.form.getRawValue(),
  });

  protected readonly dateRangeInvalid = computed(() => {
    const { start, end } = this.formValue();
    return !!start && !!end && end.getTime() <= start.getTime();
  });

  protected readonly searchDisabled = computed(() => {
    const v = this.formValue();
    return (
      this.store.loading() ||
      this.dateRangeInvalid() ||
      !v.property_id ||
      !v.room_type_id ||
      !v.start ||
      !v.end ||
      !v.quantity ||
      v.quantity < 1
    );
  });

  ngOnInit(): void {
    void this.store.loadReferenceData();
  }

  search(): void {
    if (this.searchDisabled()) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    void this.store.search({
      property_id: v.property_id!,
      room_type_id: v.room_type_id!,
      start: toIsoDate(v.start!),
      end: toIsoDate(v.end!),
      quantity: v.quantity,
      adults: v.adults,
      children: v.children,
    });
  }

  startReservation(): void {
    const result = this.store.result();
    if (!result || !result.sellable) {
      return;
    }
    void this.router.navigate(['/reservations/new'], {
      state: {
        property_id: result.property_id,
        room_type_id: result.room_type_id,
        start: result.start,
        end: result.end,
        quantity: result.quantity,
        adults: this.form.getRawValue().adults,
        children: this.form.getRawValue().children,
      },
    });
  }
}
