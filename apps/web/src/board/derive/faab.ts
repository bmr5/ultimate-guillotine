/**
 * How a team's remaining FAAB reads wherever the board shows it: `$715`, or `$—` for a team
 * with no `team_season_state` row.
 *
 * Ben, 2026-09-10, on seeing `FAAB 710` in the position view: "why FAAB # just put the number
 * and $". The budget is denominated in dollars — the league's unused auction dollars convert
 * into it, trades are priced in it, and Sleeper shows it with the sign — so the sign says what
 * the word did. This reverses a review minor of 2026-09-09 that took the sign off as "not
 * money"; that was the reviewer's guess, not a ruling.
 *
 * The word survives only in the sr-only copy beside each figure (`FAAB $715`), where `$715`
 * read out on its own could be a price of anything.
 *
 * Spelled once here because the card and the position view each used to build their own, and
 * had drifted to `75 FAAB` on one and `FAAB 715` on the other.
 */
export const FAAB_LABEL = "FAAB";

/** Shown in place of the figure when the team has no `team_season_state` row. */
export const FAAB_UNKNOWN_TEXT = "$—";

export function formatFaab(faabRemaining: number | null): string {
  return faabRemaining === null ? FAAB_UNKNOWN_TEXT : `$${faabRemaining}`;
}
