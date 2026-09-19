import { ChangeDetectionStrategy, Component, computed, inject, output, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatListModule } from '@angular/material/list';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { GuestStore } from '../store/guest.store';
import { GuestProfile } from '../models/guest.model';

/** The minimal guest-identification UX a reservation needs: search by
 * email/phone substring, pick a match, or resolve (find-or-create) a new
 * one by identity. Not a guest-management screen — no preferences,
 * consent, ID documents, or merge UI (out of A2 scope). */
@Component({
  selector: 'app-guest-search',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatListModule,
    MatProgressSpinnerModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './guest-search.html',
  styleUrl: './guest-search.scss',
})
export class GuestSearch {
  private readonly fb = inject(FormBuilder);
  protected readonly store = inject(GuestStore);

  readonly guestSelected = output<GuestProfile>();

  protected readonly showCreateForm = signal(false);

  protected readonly searchForm = this.fb.nonNullable.group({
    q: [''],
  });

  // `FormGroup.value`/`.valid` are plain properties, not signals — a
  // `computed()` reading them directly would never re-evaluate as the user
  // types (see login.ts's identical fix). `valueChanges` is the actual
  // reactive source, so it drives these signals instead.
  private readonly searchValue = toSignal(this.searchForm.valueChanges, {
    initialValue: this.searchForm.getRawValue(),
  });
  protected readonly searchDisabled = computed(
    () => this.store.loading() || !(this.searchValue().q ?? '').trim(),
  );

  protected readonly createForm = this.fb.nonNullable.group({
    email: [''],
    phone: [''],
    given_name: [''],
    family_name: [''],
  });
  private readonly createValue = toSignal(this.createForm.valueChanges, {
    initialValue: this.createForm.getRawValue(),
  });
  protected readonly createDisabled = computed(() => {
    const { email, phone } = this.createValue();
    return this.store.loading() || (!(email ?? '').trim() && !(phone ?? '').trim());
  });

  search(): void {
    const q = this.searchForm.getRawValue().q.trim();
    if (!q) {
      return;
    }
    void this.store.search(q);
  }

  select(guest: GuestProfile): void {
    this.store.select(guest);
    this.guestSelected.emit(guest);
  }

  toggleCreateForm(): void {
    this.showCreateForm.set(!this.showCreateForm());
  }

  async createGuest(): Promise<void> {
    const { email, phone, given_name, family_name } = this.createForm.getRawValue();
    const guest = await this.store.resolve({
      email: email.trim() || null,
      phone: phone.trim() || null,
      given_name: given_name.trim(),
      family_name: family_name.trim(),
    });
    if (guest) {
      this.showCreateForm.set(false);
      this.createForm.reset({ email: '', phone: '', given_name: '', family_name: '' });
      this.guestSelected.emit(guest);
    }
  }
}
