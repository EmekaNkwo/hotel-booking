import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTableModule } from '@angular/material/table';

import { GuestStore } from '../store/guest.store';
import { EmptyState } from '../../../shared/ui/empty-state/empty-state';
import { Pagination } from '../../../shared/ui/pagination/pagination';

/** `/guests` — search (the actual `?q=` contract `GuestListView` supports,
 * apps/guests/api, A0) plus a minimal create form. No arbitrary client-side
 * filter beyond that one backend-supported field; pagination is
 * server-driven via `store.nextPage()`/`previousPage()` (R1.1). */
@Component({
  selector: 'app-guest-list-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatTableModule,
    EmptyState,
    Pagination,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './guest-list-page.html',
  styleUrl: './guest-list-page.scss',
})
export class GuestListPage implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  protected readonly store = inject(GuestStore);

  protected readonly columns = ['name', 'primary_email', 'primary_phone', 'status', 'actions'];
  protected readonly showCreateForm = signal(false);

  protected readonly searchForm = this.fb.nonNullable.group({ q: [''] });
  protected readonly searchDisabled = computed(() => this.store.loading());

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

  ngOnInit(): void {
    void this.store.search('');
  }

  search(): void {
    void this.store.search(this.searchForm.getRawValue().q.trim());
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
      this.createForm.reset({ email: '', phone: '', given_name: '', family_name: '' });
      this.showCreateForm.set(false);
      await this.router.navigate(['/guests', guest.id]);
    }
  }
}
