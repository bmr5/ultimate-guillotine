import { COVERAGE_GATE_PCT } from "./projection";
import type { StarterSlotRow } from "./roster";

/**
 * The Sleeper statuses that mean the player is not on the field this week.
 *
 * Ben's report: "his TE is injured with a 0 projection, and his card says `partial` as if the
 * data were missing." The board could not tell the two apart, because a starter with no
 * projection looks identical whatever the reason. These six are the reason.
 *
 * Counted off the live players feed on 2026-09-09: `IR` 198, `PUP` 38, `Out` 21, `Sus` 11,
 * `COV` 2, `DNR` 2. `Questionable` (362) and `Doubtful` (1) are deliberately not here — a doubt
 * is not an absence, and a questionable starter still has a projection worth summing. `NA`
 * (95) is Sleeper's bookkeeping flag for a player who is not on an active roster, not a ruling
 * on this week's game, so it does not take a starter out of the lineup either.
 */
export const UNAVAILABLE_STATUSES = [
  "Out",
  "IR",
  "PUP",
  "Sus",
  "COV",
  "DNR",
] as const;

export type UnavailableStatus = (typeof UNAVAILABLE_STATUSES)[number];

/** The two statuses that mark a roster row without taking the player out of the lineup. */
export const TENTATIVE_STATUSES = ["Questionable", "Doubtful"] as const;

/**
 * The short form each status is shown as on a roster row. `Questionable` and `Doubtful` earn
 * one letter because they are the common ones and the row has no space for the word; the six
 * unavailable statuses are already short and are shown as Sleeper spells them.
 */
export const INJURY_TAGS: Record<string, string> = {
  Out: "Out",
  IR: "IR",
  PUP: "PUP",
  Sus: "Sus",
  COV: "COV",
  DNR: "DNR",
  NA: "NA",
  Questionable: "Q",
  Doubtful: "D",
};

/** What each tag means in words, for the `title` a reader hovers or a screen reader reads. */
export const INJURY_TITLES: Record<string, string> = {
  Out: "Out",
  IR: "Injured reserve",
  PUP: "Physically unable to perform",
  Sus: "Suspended",
  COV: "COVID-19 list",
  DNR: "Did not report",
  NA: "Not on an active roster",
  Questionable: "Questionable",
  Doubtful: "Doubtful",
};

/** The chip's wording, singular and plural, kept here so the card and its tests cannot drift. */
export const OUT_STARTERS_SINGULAR = "starter out";
export const OUT_STARTERS_PLURAL = "starters out";

/** What the out chip's tooltip leads with, before the names. */
export const OUT_STARTERS_TITLE_PREFIX = "Out starters: ";

/**
 * A status as the sync would have stored it: trimmed, and empty-to-null. The column is
 * check-constrained and `load_players` already normalises, so this is belt and braces for a
 * frozen snapshot or a hand-written test fixture rather than a real code path.
 */
export function normalizeInjuryStatus(
  raw: string | null | undefined,
): string | null {
  const status = (raw ?? "").trim();
  return status === "" ? null : status;
}

/** Whether a status means the player is not playing. */
export function isUnavailable(raw: string | null | undefined): boolean {
  const status = normalizeInjuryStatus(raw);
  return (
    status !== null &&
    UNAVAILABLE_STATUSES.includes(status as UnavailableStatus)
  );
}

export interface InjuryTag {
  /** The status as stored, normalised. */
  status: string;
  /** The short form the row shows. */
  tag: string;
  /** The full wording, for a `title` and for a screen reader. */
  title: string;
  /** True when the status is one of `UNAVAILABLE_STATUSES`. */
  isUnavailable: boolean;
}

/**
 * The tag a roster row carries for a status, or null when there is nothing to say.
 *
 * A status this build does not recognise is shown as its own spelling rather than dropped:
 * "something is flagged" is more useful than silence. It is not treated as unavailable, because
 * guessing a player out of a lineup is the worse error. The sync maps a status outside Sleeper's
 * known vocabulary to null rather than storing it (see `KNOWN_INJURY_STATUSES` in `players.py`),
 * so in practice this only fires for a stale bundle reading a row a newer build wrote.
 */
export function injuryTag(raw: string | null | undefined): InjuryTag | null {
  const status = normalizeInjuryStatus(raw);
  if (status === null) {
    return null;
  }
  return {
    status,
    tag: INJURY_TAGS[status] ?? status,
    title: INJURY_TITLES[status] ?? status,
    isUnavailable: isUnavailable(status),
  };
}

export interface OutStarter {
  sleeperPlayerId: string;
  fullName: string;
  /** The status as stored: `Out`, `IR`, … */
  status: string;
  /** The same status in words, for the chip's tooltip. */
  title: string;
  /**
   * The projection this out starter carries, if any.
   *
   * Sleeper keeps publishing a number for some players it has already flagged, so an out starter
   * can be inside `starters_projected`. Taking him out of the coverage denominator while leaving
   * him in the numerator would credit the team for a projection nobody is going to score, which
   * is how a lineup with a genuine hole in it read as 100 percent covered.
   */
  projectedPoints: number | null;
}

/**
 * The starters who are not playing, in lineup order.
 *
 * Reads the laid-out lineup rather than the raw roster so an empty slot cannot be mistaken for
 * an injury and so the order is the league's own. Pure: the rows are only read.
 */
export function outStarters(rows: readonly StarterSlotRow[]): OutStarter[] {
  const out: OutStarter[] = [];
  for (const row of rows) {
    if (row.kind !== "filled") {
      continue;
    }
    const tag = injuryTag(row.player.injuryStatus);
    if (tag === null || !tag.isUnavailable) {
      continue;
    }
    out.push({
      sleeperPlayerId: row.player.sleeperPlayerId,
      fullName: row.player.fullName,
      status: tag.status,
      title: tag.title,
      projectedPoints: row.player.projectedPoints,
    });
  }
  return out;
}

export interface StarterAvailabilityInput {
  /** The lineup, from `layoutStarters` — empties included. */
  starterRows: readonly StarterSlotRow[];
  /** `team_week_projections.starters_projected`; null when the week has no row. */
  startersProjected: number | null;
  /** `team_week_projections.starter_slots`; null when the week has no row. */
  starterSlots: number | null;
  /** The empty-slot count the card shows, already resolved against the projection row. */
  emptySlots: number;
}

export interface StarterAvailability {
  /** Who is out, in lineup order. */
  outStarters: OutStarter[];
  outCount: number;
  /**
   * Coverage over the slots anybody could have projected — the lineup less the out starters
   * and the empty slots, and the numerator less any projection an out starter still carries.
   * null when the week has no projection row, in which case there is no coverage claim to make
   * either way.
   */
  adjustedCoveragePct: number | null;
  /** True when coverage is short of the gate for a reason other than an out starter. */
  isPartial: boolean;
  /** `1 starter out` / `2 starters out`, or null when nobody is. */
  outChipText: string | null;
  /** The names and statuses behind the chip, or null when there is no chip. */
  outChipTitle: string | null;
}

/**
 * What the card says about its lineup: who is out, and whether what remains is still short.
 *
 * The rule Ben asked for. An out starter is *reported as out*, not counted as missing data:
 * nobody can project a player who is not playing, so he leaves the coverage denominator the
 * same way an empty slot already did — and, if Sleeper published a number for him anyway, the
 * numerator too, because a projection for a player who is not on the field is not coverage of
 * the lineup that is. What is left — the projections of the fit starters over the slots that
 * had a fit player in them — is measured against the same 95 percent gate the data layer and
 * Game Pulse use, and only that decides the `partial` chip.
 *
 * The adjusted figure can land either side of the row's own `coverage_pct` — the denominator
 * shrinks by every out starter, the numerator by the ones Sleeper projected anyway — so this is
 * not a strictly kinder reading of the week. It is still only ever a *suppressor* on the card:
 * `TeamCard` shows the chip when the data layer's own caveat is set and this does not explain it
 * away, so availability can silence a `partial` the data layer raised but never raise its own.
 *
 * Pure: reads its input and returns fresh objects.
 */
export function resolveStarterAvailability(
  input: StarterAvailabilityInput,
): StarterAvailability {
  const { starterRows, startersProjected, starterSlots, emptySlots } = input;
  const out = outStarters(starterRows);
  const outCount = out.length;

  // An out starter Sleeper still publishes a number for is counted in `starters_projected`.
  // He leaves the numerator with the denominator, so the figure describes the players who are
  // actually going to play; otherwise a lineup with one out starter and one unprojected fit one
  // read as fully covered.
  const projectedWhileOut = out.filter(
    (starter) => starter.projectedPoints !== null,
  ).length;

  let adjustedCoveragePct: number | null = null;
  if (startersProjected !== null && starterSlots !== null) {
    const coverable = starterSlots - outCount - emptySlots;
    const covered = Math.max(0, startersProjected - projectedWhileOut);
    // Nothing left to cover is full coverage, not zero: a lineup that is entirely out or
    // entirely empty has no missing projection to complain about.
    adjustedCoveragePct =
      coverable <= 0
        ? 100
        : Math.min(100, Math.max(0, (covered / coverable) * 100));
  }

  return {
    outStarters: out,
    outCount,
    adjustedCoveragePct,
    isPartial:
      adjustedCoveragePct !== null && adjustedCoveragePct < COVERAGE_GATE_PCT,
    outChipText:
      outCount === 0
        ? null
        : `${outCount} ${
            outCount === 1 ? OUT_STARTERS_SINGULAR : OUT_STARTERS_PLURAL
          }`,
    outChipTitle:
      outCount === 0
        ? null
        : OUT_STARTERS_TITLE_PREFIX +
          out
            .map((starter) => `${starter.fullName} (${starter.title})`)
            .join(", "),
  };
}
