import { resolveOwnerLabel } from "@/board/derive/join";

import type { HistoryMemberRow } from "../fetchers";

/**
 * The public label for a member id, or `null` when no label can be honestly written.
 *
 * `null` — not a placeholder string — when the id is absent or names nobody in `members`: the
 * caller decides how an unresolved owner reads, and only the caller knows whether it is
 * writing a champion line, an elimination line or a filter option. `UNKNOWN_OWNER` is the
 * usual answer, but "Unlisted" is the right one on a season card.
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
