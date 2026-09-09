import type { BoardTeam } from "../types";

/**
 * Combining marks left behind by the NFD decomposition below. Sleeper spells some players with
 * accents (`Puka Nacuá`) and the league's owner labels carry them too, so a term typed on a
 * plain keyboard has to reach them — and an accented term has to reach an unaccented row.
 */
const COMBINING_MARKS = /\p{Mark}/gu;

/**
 * The one text shape both sides of a comparison are folded into: decomposed, unaccented, and
 * lower-cased. Applied to the needle and to every haystack, never to what is rendered.
 */
export function normalizeSearchText(value: string): string {
  return value.normalize("NFD").replace(COMBINING_MARKS, "").toLowerCase();
}

export interface TeamSearchMatch {
  matches: boolean;
  /**
   * The `sleeperPlayerId` of every roster row the term hit, in roster order. Empty when the team
   * matched by owner or team name alone — the card highlights exactly these rows.
   */
  matchedPlayerIds: string[];
}

/**
 * Matches a team against the header's filter across the owner label, the team name, and every
 * player on the roster. A blank term matches everything, so an empty box is not a filter.
 */
export function matchTeam(team: BoardTeam, term: string): TeamSearchMatch {
  const needle = normalizeSearchText(term.trim());
  if (needle === "") {
    return { matches: true, matchedPlayerIds: [] };
  }

  const matchedPlayerIds = team.roster
    .filter((player) => normalizeSearchText(player.fullName).includes(needle))
    .map((player) => player.sleeperPlayerId);

  const nameHit =
    normalizeSearchText(team.ownerName).includes(needle) ||
    normalizeSearchText(team.teamName).includes(needle);

  // A name hit never suppresses the player hits: a term that matches both the team and one of
  // its players still has to highlight that player.
  return {
    matches: nameHit || matchedPlayerIds.length > 0,
    matchedPlayerIds,
  };
}

export interface FilteredBoard {
  teams: BoardTeam[];
  /** Teams matched by a player name auto-expand so the matched player is visible. */
  autoExpandTeamIds: number[];
  matchedPlayerIds: Set<string>;
}

/**
 * Filters the board in place order — the caller's sort is preserved, teams are passed through by
 * reference, and nothing is re-sorted here.
 */
export function filterTeams(teams: BoardTeam[], term: string): FilteredBoard {
  const kept: BoardTeam[] = [];
  const autoExpandTeamIds: number[] = [];
  const matchedPlayerIds = new Set<string>();

  for (const team of teams) {
    const match = matchTeam(team, term);
    if (!match.matches) {
      continue;
    }
    kept.push(team);
    if (match.matchedPlayerIds.length > 0) {
      autoExpandTeamIds.push(team.teamId);
      for (const id of match.matchedPlayerIds) {
        matchedPlayerIds.add(id);
      }
    }
  }

  return { teams: kept, autoExpandTeamIds, matchedPlayerIds };
}
