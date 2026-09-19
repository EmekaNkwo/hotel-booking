import { JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { RoomStore } from '../store/room.store';
import { RoomStatusBadge } from '../components/room-status-badge';

/** `/rooms/:id` — the authoritative room, rendered exactly as
 * `RoomSerializer` returns it. No state-transition controls: M3's
 * `RoomStateMachine` owns those transitions (via reservation/allocation/
 * housekeeping flows) and A4 must not bypass it. */
@Component({
  selector: 'app-room-detail-page',
  imports: [JsonPipe, RoomStatusBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './room-detail-page.html',
  styleUrl: './room-detail-page.scss',
})
export class RoomDetailPage implements OnInit {
  private readonly route = inject(ActivatedRoute);
  protected readonly store = inject(RoomStore);

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    void this.store.loadOne(id);
  }

  protected hasAttributes(attributes: Record<string, unknown>): boolean {
    return Object.keys(attributes).length > 0;
  }
}
