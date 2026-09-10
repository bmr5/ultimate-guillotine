import { resolveOwnerLabel } from "@/board/derive/join";

import type { HistoryMemberRow } from "../fetchers";

/**
 * What an owner these pages cannot name reads as.
 *
 * Ben's ruling: he is not going to map every old nickname in the trade catalog, and an
 * unmapped party is almost always somebody who has left the league — so the honest word for
 * one is "former manager", not "unidentified owner" or "Unlisted". Both of those read as a
 * hole in the data; this reads as the fact it usually is. A manager who is worth naming gets
 * a profile (`ug members former add`) and stops falling in here at all.
 */
export const FORMER_MANAGER = "Former manager";

/**
 * The same thing mid-sentence, where a count is what the page has: "a former manager",
 * "3 former managers". Singular is the article rather than "1", which reads as a tally of
 * people rather than as one of them.
 */
export function formerManagerPhrase(count: number): string {
  return count === 1 ? "a former manager" : `${count} former managers`;
}

/**
 * What a placing reads as when `season_results` recorded nobody in it at all.
 *
 * Not "Former manager": that claims a person the sheet never named. A season whose
 * `champion_member_id` is null is a season nobody has loaded a champion for — a hole in the
 * data, and the one case where saying so is the honest answer.
 */
export const NOT_RECORDED = "Not recorded";

/**
 * The word for one of a season's placings, from its label and the id the row carried.
 *
 * Both facts are needed and neither is enough. `ownerLabelFor` answers `null` for an id that
 * names nobody *and* for no id at all, so a champion line reading off the label alone cannot
 * tell "a manager who has left" from "the sheet never recorded a champion" and prints the
 * same word for both. The id separates them: present means a person the directory cannot
 * name, absent means no person was recorded.
 *
 * Shared by the season cards and the winners strip so the two can never drift into
 * describing the same season differently.
 */
export function seasonPlacingLabel(
  label: string | null,
  memberId: number | null,
): string {
  if (label !== null) return label;
  return memberId === null ? NOT_RECORDED : FORMER_MANAGER;
}

/**
 * The public label for a member id, or `null` when no label can be honestly written.
 *
 * `null` — not a placeholder string — when the id is absent or names nobody in `members`: the
 * caller decides how an unresolved owner reads, and only the caller knows whether it is
 * writing a champion line, an elimination line or a filter option. `FORMER_MANAGER` is the
 * usual answer; the owner filter's answer is to leave the option out entirely.
 *
 * The label itself is `resolveOwnerLabel`'s — nickname first, then the Sleeper display name.
 * `members.display_name` is a real name and never reaches a public page.
 */
export function ownerLabelFor(
  memberId: number | null,
  members: readonly HistoryMemberRow[],
): string | null {
  if (memberId === null) return null;
  const member = members.find((candidate) => candidate.id === memberId);
  return member === undefined ? null : resolveOwnerLabel(member);
}

/**
 * Ben (2026-09-10): "just for something funny put an asterisk after Ben R." One name, one
 * asterisk, on the history page only; nothing else about the label changes.
 */
export const ASTERISKED_CHAMPION = "Ben R";

export function championDisplay(label: string): string {
  return label === ASTERISKED_CHAMPION ? `${label}*` : label;
}
