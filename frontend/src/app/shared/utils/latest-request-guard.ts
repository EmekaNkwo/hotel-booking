/** R0.10: guards a Store signal against an out-of-order (stale) async
 * result overwriting a newer one — e.g. navigating from `/bookings/5` to
 * `/bookings/6` before booking 5's in-flight response resolves, or a
 * `loadOne()` and a mutation that both write `current` resolving out of
 * order. Each call that will eventually write the guarded signal takes a
 * token via `next()`; only the call still holding the CURRENT token when
 * its async work resolves is allowed to apply its result via `isCurrent()`.
 *
 * One instance per guarded signal (not per method) — a `loadOne()` and a
 * mutation that both write `current` must share the same guard, or a
 * slow-to-resolve `loadOne()` could still stomp a mutation's fresher
 * result. No subscriptions, no teardown — a plain counter, so there is
 * nothing to leak.
 */
export class LatestRequestGuard {
  private token = 0;

  /** Call once at the start of the async operation; keep the returned
   * token to check with `isCurrent()` once the result is ready. */
  next(): number {
    return ++this.token;
  }

  /** True if `token` is still the most recently issued one — i.e. no
   * newer call (to this same guard) has started since. */
  isCurrent(token: number): boolean {
    return token === this.token;
  }
}
