import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { NotificationStore } from '../store/notification.store';
import { NotificationStatusBadge } from '../components/notification-status-badge';

/** `/notifications/:id` — the authoritative notification job, rendered
 * exactly as returned. Read-only: no `DeliveryAttempt` data is shown
 * because no endpoint exposes it, and no retry/requeue action exists
 * because A0 exposes none — delivery stays Celery/projector-driven. */
@Component({
  selector: 'app-notification-detail-page',
  imports: [JsonPipe, RouterLink, NotificationStatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './notification-detail-page.html',
  styleUrl: './notification-detail-page.scss',
})
export class NotificationDetailPage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  protected readonly store = inject(NotificationStore);

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    void this.store.loadOne(id);
  }
}
