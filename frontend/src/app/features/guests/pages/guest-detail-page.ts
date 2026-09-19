import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { GuestStore } from '../store/guest.store';

/** `/guests/:id` — the authoritative GuestProfile, rendered exactly as
 * `GuestProfileSerializer` returns it. No preferences/consent/booking
 * context is shown because no API endpoint exposes any of that today (A0's
 * guest surface is identity fields only) — inventing those would violate
 * "only display information actually provided by the API". No edit form:
 * `GuestService` has no update operation, only `resolve()` (find-or-create,
 * never mutates an existing profile) — confirmed by reading
 * apps/guests/services.py and apps/guests/api/views.py. */
@Component({
  selector: 'app-guest-detail-page',
  imports: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './guest-detail-page.html',
  styleUrl: './guest-detail-page.scss',
})
export class GuestDetailPage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  protected readonly store = inject(GuestStore);

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    void this.store.loadOne(id);
  }
}
