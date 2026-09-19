/** Generates one idempotency key per user command (A0's `idempotency_key`
 * fields). Callers must generate this ONCE when the user initiates a
 * command and reuse the SAME value if the user deliberately retries the
 * identical request — never mint a new key per network attempt, and never
 * share one key across two different commands. */
export function generateIdempotencyKey(): string {
  return crypto.randomUUID();
}
