import type { BoardTeam } from "../types";

/**
 * Rich, medium and poor by FAAB, split with one-dimensional k-means (k = 3).
 *
 * Ben (2026-09-10): "make a fun filter that splits the rosters into tiers of rich medium poor
 * with math". Terciles would put six teams in every tier however the money is spread; k-means
 * finds the three natural clusters, so a league with two whales and sixteen paupers reads that
 * way. Centroids start at the minimum, the median and the maximum, so the result is
 * deterministic, and a tie goes to the richer tier.
 */

export type TierKey = "rich" | "medium" | "poor";

export interface FaabTier {
  key: TierKey;
  label: string;
  /** Teams in the tier, richest first. */
  teams: BoardTeam[];
  /** The tier's FAAB span, null for an empty tier. */
  min: number | null;
  max: number | null;
  /** The cluster centre the maths settled on. */
  centroid: number | null;
}

export interface FaabTiers {
  tiers: [FaabTier, FaabTier, FaabTier];
  /** Teams with no FAAB on file, listed apart so they never distort a cluster. */
  unknown: BoardTeam[];
  method: string;
}

export const TIER_LABELS: Record<TierKey, string> = {
  rich: "Rich",
  medium: "Medium",
  poor: "Poor",
};

export const TIER_METHOD = "k-means, k = 3, on FAAB remaining";

const MAX_ITERATIONS = 50;

function median(sorted: readonly number[]): number {
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
}

/** Assign each value to the nearest centroid; ties go to the higher index (the richer tier). */
function assign(
  values: readonly number[],
  centroids: readonly number[],
): number[] {
  return values.map((value) => {
    let best = 0;
    for (let index = 1; index < centroids.length; index += 1) {
      if (
        Math.abs(value - centroids[index]) <= Math.abs(value - centroids[best])
      ) {
        best = index;
      }
    }
    return best;
  });
}

/** One-dimensional Lloyd's algorithm over `values`, returning each value's cluster index (0 = poorest). */
export function kMeansThree(values: readonly number[]): number[] {
  if (values.length === 0) return [];
  const sorted = [...values].sort((a, b) => a - b);
  let centroids = [sorted[0], median(sorted), sorted[sorted.length - 1]];
  let labels = assign(values, centroids);
  for (let iteration = 0; iteration < MAX_ITERATIONS; iteration += 1) {
    const next = centroids.map((centroid, index) => {
      const members = values.filter((_, i) => labels[i] === index);
      return members.length === 0
        ? centroid
        : members.reduce((sum, v) => sum + v, 0) / members.length;
    });
    const nextLabels = assign(values, next);
    const settled = nextLabels.every((label, i) => label === labels[i]);
    centroids = next;
    labels = nextLabels;
    if (settled) break;
  }
  return labels;
}

export function faabTiers(teams: readonly BoardTeam[]): FaabTiers {
  const known = teams.filter((team) => team.faabRemaining !== null);
  const unknown = teams.filter((team) => team.faabRemaining === null);
  const values = known.map((team) => team.faabRemaining as number);
  const labels = kMeansThree(values);
  const keys: TierKey[] = ["poor", "medium", "rich"];
  const buckets: Record<TierKey, BoardTeam[]> = {
    rich: [],
    medium: [],
    poor: [],
  };
  known.forEach((team, index) => buckets[keys[labels[index]]].push(team));
  const build = (key: TierKey): FaabTier => {
    const members = [...buckets[key]].sort(
      (a, b) => (b.faabRemaining as number) - (a.faabRemaining as number),
    );
    const amounts = members.map((team) => team.faabRemaining as number);
    return {
      key,
      label: TIER_LABELS[key],
      teams: members,
      min: amounts.length ? Math.min(...amounts) : null,
      max: amounts.length ? Math.max(...amounts) : null,
      centroid: amounts.length
        ? Math.round(amounts.reduce((sum, v) => sum + v, 0) / amounts.length)
        : null,
    };
  };
  return {
    tiers: [build("rich"), build("medium"), build("poor")],
    unknown,
    method: TIER_METHOD,
  };
}

/**
 * A line that makes each tier memorable (Ben, 2026-09-10: "so brandon can brag about being the
 * richest"). Names the richest and the poorest so the bragging rights are explicit.
 */
export function tierBlurb(tier: FaabTier): string {
  const top = tier.teams[0];
  const bottom = tier.teams[tier.teams.length - 1];
  if (!top || !bottom) return "Nobody here. Yet.";
  const n = tier.teams.length;
  switch (tier.key) {
    case "rich":
      return n === 1
        ? `${top.ownerName} alone at the top with $${top.faabRemaining}. The league's bank.`
        : `Old money. ${top.ownerName} leads the league at $${top.faabRemaining}; the other ${n - 1 === 1 ? "one" : n - 1} could still buy a starter on a whim.`;
    case "medium":
      return `Comfortable. Enough to win a bid, not enough to scare anyone. ${top.ownerName} is one good week from the top tier.`;
    default:
      return n === 1
        ? `${bottom.ownerName} has $${bottom.faabRemaining} and a prayer.`
        : `Scraping by. ${bottom.ownerName} brings up the rear at $${bottom.faabRemaining}; every waiver claim here is a decision.`;
  }
}

/** The single richest team in the league, for the crown. */
export function richestTeam(tiers: FaabTiers): BoardTeam | null {
  return tiers.tiers[0].teams[0] ?? null;
}
