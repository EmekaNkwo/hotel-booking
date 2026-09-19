import { LatestRequestGuard } from './latest-request-guard';

describe('LatestRequestGuard', () => {
  it('a single call is current until superseded', () => {
    const guard = new LatestRequestGuard();
    const token = guard.next();
    expect(guard.isCurrent(token)).toBe(true);
  });

  it('an older token is no longer current once a newer one is issued', () => {
    const guard = new LatestRequestGuard();
    const older = guard.next();
    const newer = guard.next();
    expect(guard.isCurrent(older)).toBe(false);
    expect(guard.isCurrent(newer)).toBe(true);
  });

  it('out-of-order resolution: the LATE-STARTING call still wins if it resolves not-last', () => {
    // Simulates: call A starts, call B starts (supersedes A), B resolves
    // first, A resolves last — A must NOT be considered current even
    // though it resolved after B, because token order (start order) is
    // what determines "latest", not resolution order.
    const guard = new LatestRequestGuard();
    const tokenA = guard.next();
    const tokenB = guard.next();
    // B "resolves" first — still current.
    expect(guard.isCurrent(tokenB)).toBe(true);
    // A "resolves" after — must be stale.
    expect(guard.isCurrent(tokenA)).toBe(false);
  });
});
