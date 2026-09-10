import type { CSSProperties } from "react";

/**
 * The one entrance the site has.
 *
 * Ben, 2026-09-10: "have them properly use suspense and animate in so everything just feels
 * smooth." Every surface that mounts — the shell, a page's header strip, each card as its data
 * lands — settles into place with the same short motion, in one cascade from the top of the page
 * down. It is one vocabulary applied everywhere rather than a choreography per section, which is
 * what keeps a page of eighteen cards from reading as eighteen effects.
 *
 * The rule itself is `.reveal` in `globals.css`. It reads `--reveal-index` for the element's
 * place in the cascade and turns it into a delay; while the intro curtain is still up
 * (`[data-intro="playing"]`) the animation is held paused, so a page that loaded under the
 * curtain makes its entrance as the curtain parts and not before.
 */
export const REVEAL_CLASS = "reveal";

/** The custom property `.reveal` derives its delay from; set through `revealStyle`. */
export const REVEAL_INDEX_PROPERTY = "--reveal-index";

/**
 * Places past this one share the same delay. The cascade exists to lead the eye down the page,
 * and ten steps do that; a twenty-card list trailing in one card at a time for a full second
 * would be the list making the reader wait for it.
 */
export const REVEAL_STAGGER_CAP = 10;

/**
 * The inline style that gives an element its place in the cascade: `0` is the first thing on
 * the page to settle, `1` the next. Anything that is not a whole, non-negative place is read as
 * the front of the cascade rather than thrown.
 */
export function revealStyle(index: number): CSSProperties {
  const place = Number.isFinite(index)
    ? Math.min(REVEAL_STAGGER_CAP, Math.max(0, Math.floor(index)))
    : 0;
  return { [REVEAL_INDEX_PROPERTY]: place } as CSSProperties;
}
