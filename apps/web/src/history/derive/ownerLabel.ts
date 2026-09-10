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
