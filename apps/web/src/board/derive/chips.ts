/**
 * Which chips a team card is allowed to say at once.
 *
 * Round 2 reserved the owner's name against however many chips the card happened to carry, and
 * the cost was the thing that made the rule necessary: a two-chip card blanked the owner's name
 * on a phone, and the fallback row that caught a third chip added its own band to every card in
 * the grid. Both were symptoms of a chip set that could hold four members at once.
 *
 * So the set is mutually limited rather than merely reserved for. At most two chips can ever be
 * on a card, both of them short:
 *
 * - Eliminated → the elimination and nothing else. Its projection is not live; there is nothing
 *   about a frozen number that needs a caveat, and `partial` or `Projection unavailable` beside
 *   `Eliminated week 4` reads as a data problem rather than as a ruling.
 * - No projection → `Projection unavailable` and nothing else. With no number there is no
 *   coverage to qualify, and an out starter is a footnote on a projection that does not exist.
 * - Otherwise → `N starter(s) out` when any starter is out, plus `partial` when the suppression
 *   rule in `TeamCard` leaves it. This is the only two-chip case.
 *
 * Pure and separate from the component so the rule can be read and tested on its own — the
 * component's job is the wording and the tooltip, not the arithmetic of what is allowed.
 */

/** The card states that can wear a chip, named by the `data-chip` handle each one renders. */
export type ChipKind = "out" | "partial" | "unavailable" | "eliminated";

export interface ChipSetInput {
  /**
   * Whether the team is out of the league. `is_eliminated`, not `eliminated_week`: the week is
   * nullable, so a provisional elimination can be known without one, and it is the elimination
   * rather than the week that silences the rest of the set.
   */
  isEliminated: boolean;
  /** Whether the week has a projection to qualify at all. */
  hasProjection: boolean;
  /** How many of this lineup's starters Sleeper has flagged as not playing. */
  outCount: number;
  /** Whether the data layer's `partial` caveat survived the availability suppression. */
  isPartial: boolean;
}

/**
 * The most chips a card can carry, which is what keeps the chip line to one line. Derived from
 * the rule below rather than asserted next to it, so the two cannot drift.
 */
export const MAX_CHIPS = 2;

/**
 * The chips this card may show, in reading order.
 *
 * Order is the order a reader wants them: what is happening to the roster first, then the
 * footnote on the number. The elimination and the missing-projection states are alone on their
 * cards, so they have no order to keep.
 */
export function resolveChipKinds(input: ChipSetInput): ChipKind[] {
  if (input.isEliminated) {
    return ["eliminated"];
  }
  if (!input.hasProjection) {
    return ["unavailable"];
  }
  const kinds: ChipKind[] = [];
  if (input.outCount > 0) {
    kinds.push("out");
  }
  if (input.isPartial) {
    kinds.push("partial");
  }
  return kinds;
}
