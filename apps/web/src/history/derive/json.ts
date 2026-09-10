/**
 * Whether a `jsonb` value is worth reading fields off at all.
 *
 * None of the JSON documents these pages read — `trade_catalog.assets`,
 * `trade_revisions.terms`, `season_results.eliminations` — forbids a `null` or a bare string
 * inside its arrays, and reading a property off either throws. Every loop that walks one of
 * them narrows through this first and drops what it cannot use, so a malformed element costs
 * that one entry and not the whole page.
 *
 * One definition rather than one per reader: the two callers were guarding the same shape of
 * data against the same failure, and only one of them had the guard.
 */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
