import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';

import { HousekeepingStore } from '../store/housekeeping.store';
import { HousekeepingStatusBadge } from '../components/housekeeping-status-badge';
import { InspectionResult } from '../models/housekeeping-task.model';
import { generateIdempotencyKey } from '../../../shared/utils/idempotency-key';

/** `/housekeeping/:id` — the authoritative task, rendered exactly as
 * returned. Buttons are shown based on the currently-known `status` purely
 * as a UX convenience; the backend remains authoritative if a transition
 * is attempted anyway (a 409 renders the backend's own message, never a
 * locally-guessed one). No assignment control — A0 exposes no HTTP
 * endpoint for `HousekeepingService.assign()`. No OOS routing on a failed
 * inspection — M12 explicitly does not have one. */
@Component({
  selector: 'app-housekeeping-detail-page',
  imports: [MatButtonModule, HousekeepingStatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './housekeeping-detail-page.html',
  styleUrl: './housekeeping-detail-page.scss',
})
export class HousekeepingDetailPage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  protected readonly store = inject(HousekeepingStore);

  private readonly startKeys = new Map<number, string>();
  private readonly completeKeys = new Map<number, string>();
  private readonly inspectKeys = new Map<number, string>();

  protected readonly actionLoading = computed(() => {
    const task = this.store.current();
    return task ? this.store.isActionLoading(task.id) : false;
  });

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    void this.store.loadOne(id);
  }

  async startCleaning(): Promise<void> {
    const task = this.store.current();
    if (!task) {
      return;
    }
    const key = this.consumeKey(this.startKeys, task.id);
    const ok = await this.store.startCleaning(task.id, key);
    if (ok) {
      this.startKeys.delete(task.id);
    }
  }

  async completeCleaning(): Promise<void> {
    const task = this.store.current();
    if (!task) {
      return;
    }
    const key = this.consumeKey(this.completeKeys, task.id);
    const ok = await this.store.completeCleaning(task.id, key);
    if (ok) {
      this.completeKeys.delete(task.id);
    }
  }

  async inspect(result: InspectionResult): Promise<void> {
    const task = this.store.current();
    if (!task) {
      return;
    }
    if (result === 'fail' && !confirm('Record this room as failing inspection?')) {
      return;
    }
    const key = this.consumeKey(this.inspectKeys, task.id);
    const ok = await this.store.inspect(task.id, { result, idempotency_key: key });
    if (ok) {
      this.inspectKeys.delete(task.id);
    }
  }

  refresh(): void {
    const task = this.store.current();
    if (task) {
      void this.store.loadOne(task.id);
    }
  }

  private consumeKey(map: Map<number, string>, taskId: number): string {
    let key = map.get(taskId);
    if (!key) {
      key = generateIdempotencyKey();
      map.set(taskId, key);
    }
    return key;
  }
}
