import type { AdverseEvent, Json, TeamRisk } from "../types";

/**
 * The Guillotine Daily's odds, read off `survival_snapshots.results` and put into words.
 *
 * Ben: "want to add your monte carlo simulation %s to the actual website? just write the last
 * time it was run so people know". The number on a card is the number the chat got —
 * `formatRiskPercent` mirrors `percent()` in the Daily's `summary/render.py`, tails and all —
 * and both the chip's tooltip and the header carry the snapshot's own `snapshot_at`.
 */

/** The two columns the board reads off the row; `results` is what `results_payload` writes. */
export interface SurvivalSnapshotSource {
  snapshot_at: string;
  results: Json;
}

/**
 * The Daily's own colour thresholds — `_RED` and `_AMBER` in `summary/artifact.py` — so a red
 * figure on the board is the same figure that is red in the attached page.
 */
export const RISK_RED_THRESHOLD = 0.5;
export const RISK_AMBER_THRESHOLD = 0.2;

/** `destructive` from the red threshold, `primary` (the site's amber) from the amber one. */
export type RiskTone = "destructive" | "primary" | "muted";

export interface RiskDisplay {
  /** The chip's visible wording: `Gulag 37%`, or `Cut locked` once every game is final. */
  text: string;
  /** The same thing spelled out for a screen reader. */
  label: string;
  /** The sentence behind the chip: what the chance is of, and where the number comes from. */
  description: string;
  tone: RiskTone;
}

/** The short word on the chip, per event. The Daily's own page heads the column `Risk`. */
export const RISK_EVENT_LABELS: Record<AdverseEvent, string> = {
  gulag_entry: "Gulag",
  gulag_loss: "Cut",
  cut: "Cut",
  title_loss: "Runner-up",
};

/** The word for an event this build does not know: the figure shows, unnamed, rather than not. */
const RISK_UNKNOWN_LABEL = "Risk";

const RISK_EVENT_SPOKEN: Record<AdverseEvent, string> = {
  gulag_entry: "Chance of entering the gulag",
  gulag_loss: "Chance of losing the gulag and being cut",
  cut: "Chance of being cut",
  title_loss: "Chance of finishing runner-up",
};

const RISK_UNKNOWN_SPOKEN = "Chance of the week going against this team";

const RISK_EVENT_DESCRIPTIONS: Record<AdverseEvent, string> = {
  gulag_entry:
    "The chance this team finishes in the bottom two and enters the gulag.",
  gulag_loss: "The chance this team loses the gulag and is cut.",
  cut: "The chance this team posts the week's lowest score and is cut.",
  title_loss: "The chance this team posts the lower score in the final.",
};

const RISK_UNKNOWN_DESCRIPTION = "The chance the week goes against this team.";

/** Where the number comes from, said once in every tooltip. */
export const MONTE_CARLO_SENTENCE =
  "From the Guillotine Daily's Monte Carlo simulation of the games still to play.";

/** The settled counterpart: nothing is left to simulate, so the figure is a result. */
const SETTLED_SENTENCE =
  "From the Guillotine Daily: every game is final, so this is the result rather than a forecast.";

const ESTIMATED_SENTENCE =
  "A starter with no projection was simulated at his position's median.";

/** The events this build has words for; anything else narrows to null. */
const ADVERSE_EVENTS: ReadonlySet<string> = new Set(
  Object.keys(RISK_EVENT_LABELS),
);

function narrowAdverseEvent(value: unknown): AdverseEvent | null {
  return typeof value === "string" && ADVERSE_EVENTS.has(value)
    ? (value as AdverseEvent)
    : null;
}

/** An entry's pending-starter count, or null when it is not a number this build can read. */
function readPending(entry: unknown): number | null {
  if (typeof entry !== "object" || entry === null) {
    return null;
  }
  const pending = (entry as Record<string, unknown>).pending;
  return typeof pending === "number" && Number.isFinite(pending)
    ? pending
    : null;
}

/**
 * Every team's odds in one map, keyed by team id.
 *
 * `results` is jsonb the Daily's `results_payload` writes — one entry per live team — and is
 * narrowed on the way in for the same reason `narrowFrozenHoldings` is in `derive/join`: a
 * stored row is data some earlier build wrote, and no `tsc` run over this one can vouch for it.
 * An entry with no finite team id or probability is dropped, since without either there is
 * nothing to show or to show it on. An event this build has no word for is kept under null,
 * so a new phase in the Daily shows its figure here rather than hiding it.
 *
 * Settled is a property of the whole snapshot — no live team had a starter left to play — and
 * a pending count this build cannot read is not a zero: it withholds the words rather than
 * calling a half-played week a result.
 */
export function riskByTeamId(
  snapshot: SurvivalSnapshotSource | null | undefined,
): Map<number, TeamRisk> {
  const risks = new Map<number, TeamRisk>();
  if (snapshot === null || snapshot === undefined) {
    return risks;
  }
  const entries: unknown = snapshot.results;
  if (!Array.isArray(entries)) {
    return risks;
  }
  const settled =
    entries.length > 0 &&
    (entries as unknown[]).every((entry) => readPending(entry) === 0);

  for (const entry of entries as unknown[]) {
    if (typeof entry !== "object" || entry === null) {
      continue;
    }
    const record = entry as Record<string, unknown>;
    const teamId = record.team_id;
    const probability = record.probability;
    if (typeof teamId !== "number" || !Number.isFinite(teamId)) {
      continue;
    }
    if (typeof probability !== "number" || !Number.isFinite(probability)) {
      continue;
    }
    risks.set(teamId, {
      probability,
      adverseEvent: narrowAdverseEvent(record.adverse_event),
      isEstimated: record.is_estimated === true,
      settled,
      snapshotAt: snapshot.snapshot_at,
    });
  }
  return risks;
}

/**
 * A whole percentage with the tails named, and words once nothing is left to play — exactly
 * `percent()` in the Daily's `summary/render.py`, so the board and the chat never disagree by
 * a rounding rule. `Math.round` rounds a half up for a positive number, which is the Daily's
 * `ROUND_HALF_UP`.
 */
export function formatRiskPercent(
  probability: number,
  settled: boolean,
): string {
  if (settled) {
    if (probability >= 1) {
      return "locked";
    }
    if (probability <= 0) {
      return "safe";
    }
  }
  if (probability <= 0) {
    return "0%";
  }
  if (probability >= 1) {
    return "100%";
  }
  const hundred = probability * 100;
  if (hundred < 1) {
    return "<1%";
  }
  if (hundred > 99) {
    return ">99%";
  }
  return `${Math.round(hundred)}%`;
}

export function resolveRiskTone(probability: number): RiskTone {
  if (probability >= RISK_RED_THRESHOLD) {
    return "destructive";
  }
  if (probability >= RISK_AMBER_THRESHOLD) {
    return "primary";
  }
  return "muted";
}

/** The odds chip's wording, or null for a team with no odds this week. */
export function resolveRiskDisplay(
  risk: TeamRisk | null,
): RiskDisplay | null {
  if (risk === null) {
    return null;
  }
  const percent = formatRiskPercent(risk.probability, risk.settled);
  const event = risk.adverseEvent;
  const word = event === null ? RISK_UNKNOWN_LABEL : RISK_EVENT_LABELS[event];
  const spoken = event === null ? RISK_UNKNOWN_SPOKEN : RISK_EVENT_SPOKEN[event];
  const sentences = [
    event === null ? RISK_UNKNOWN_DESCRIPTION : RISK_EVENT_DESCRIPTIONS[event],
    risk.settled ? SETTLED_SENTENCE : MONTE_CARLO_SENTENCE,
  ];
  if (risk.isEstimated) {
    sentences.push(ESTIMATED_SENTENCE);
  }
  return {
    text: `${word} ${percent}`,
    label: `${spoken}: ${percent}`,
    description: sentences.join(" "),
    tone: resolveRiskTone(risk.probability),
  };
}
