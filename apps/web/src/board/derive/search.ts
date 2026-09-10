import type { BoardTeam } from "../types";

/**
 * Combining marks left behind by the NFD decomposition below. Sleeper spells some players with
 * accents (`Puka Nacuá`) and the league's owner labels carry them too, so a term typed on a
 * plain keyboard has to reach them — and an accented term has to reach an unaccented row.
 */
const COMBINING_MARKS = /\p{Mark}/gu;

/**
 * Curly apostrophes, in the shapes a phone keyboard, a copy-paste from Sleeper, or a word
 * processor produce. Folded to the straight one first so the punctuation strip below only has to
 * know a single spelling of the character.
 */
const SMART_APOSTROPHES = /[\u2018\u2019\u02bc\u2032]/g;

/**
 * Punctuation nobody types when searching. `Ja'Marr Chase` has to answer to `jamarr` and
 * `T.J. Hockenson` to `tj`, so both the period and the apostrophe are dropped from both sides of
 * every comparison rather than being required to line up.
 */
const DROPPED_PUNCTUATION = /['.]/g;

/** Any run of whitespace, including the double space left behind by a typo or a paste. */
const WHITESPACE_RUN = /\s+/g;

/**
 * The one text shape both sides of a comparison are folded into: decomposed, unaccented,
 * lower-cased, stripped of the punctuation searches never carry, and reduced to single spaces
 * with no edges. Applied to the needle and to every haystack, never to what is rendered.
 */
export function normalizeSearchText(value: string): string {
  return value
    .normalize("NFD")
    .replace(COMBINING_MARKS, "")
    .toLowerCase()
    .replace(SMART_APOSTROPHES, "'")
    .replace(DROPPED_PUNCTUATION, "")
    .replace(WHITESPACE_RUN, " ")
    .trim();
}

/**
 * The term split into the words that all have to land. `normalizeSearchText` already collapsed
 * the whitespace, so a single space is the only separator left; a blank term yields no tokens,
 * which is the "not filtering" case.
 */
export function tokenizeSearchTerm(term: string): string[] {
  const needle = normalizeSearchText(term);
  return needle === "" ? [] : needle.split(" ");
}

/**
 * Whether an already-normalized haystack answers every token. No tokens is "not filtering", so
 * it matches. Shared with `/trades` so a term behaves identically on both pages.
 */
export function matchesAllTokens(
  normalizedText: string,
  tokens: readonly string[],
): boolean {
  return tokens.every((token) => normalizedText.includes(token));
}

export interface TeamSearchMatch {
  matches: boolean;
  /**
   * The `sleeperPlayerId` of every roster row that answers the whole term, in roster order.
   * Empty when the team matched by owner or team name alone — the card highlights exactly these
   * rows.
   */
  matchedPlayerIds: string[];
}

/**
 * Matches a team against the header's filter across the owner label, the team name, and every
 * player on the roster. A blank term matches everything, so an empty box is not a filter.
 *
 * The term is a set of words, not one string: every word has to land somewhere in the team —
 * owner label, team name, or some player's name — so `nacua puka` finds Puka Nacua and a word
 * order nobody remembers is not a miss. A roster row is reported only when it answers the term
 * on its own, i.e. every word is in that one player's name, so the card highlights the rows the
 * search was actually about.
 */
export function matchTeam(team: BoardTeam, term: string): TeamSearchMatch {
  const tokens = tokenizeSearchTerm(term);
  if (tokens.length === 0) {
    return { matches: true, matchedPlayerIds: [] };
  }

  const playerNames = team.roster.map((player) =>
    normalizeSearchText(player.fullName),
  );
  const matchedPlayerIds = team.roster
    .filter((_, index) => matchesAllTokens(playerNames[index], tokens))
    .map((player) => player.sleeperPlayerId);

  const ownerName = normalizeSearchText(team.ownerName);
  const teamName = normalizeSearchText(team.teamName);
  const matches = tokens.every(
    (token) =>
      ownerName.includes(token) ||
      teamName.includes(token) ||
      playerNames.some((name) => name.includes(token)),
  );

  // A name hit never suppresses the player hits: a term that matches both the team and one of
  // its players still has to highlight that player.
  return { matches, matchedPlayerIds };
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
