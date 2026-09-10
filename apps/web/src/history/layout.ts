/**
 * The measurements the trade and season cards share with the placeholders that stand in for
 * them, in one place so a placeholder is the size of the card it is waiting for and nothing
 * moves when the card lands. (`src/board/layout.ts` does the same for the board.)
 */

/** The two-column card grid on the trades and history pages. */
export const CARD_GRID = "grid grid-cols-1 gap-2 sm:grid-cols-2";

/**
 * Every trade card is this tall, whatever it carries. Ben's ruling of 2026-09-09: "make sure all
 * the trade cards are the same size" — a grid where one tile is a title and the next is a wall
 * of quotation is not a grid. Room for the three header lines, a three-line quotation and a row
 * of chips; anything longer is what the modal is for.
 */
export const TRADE_CARD_HEIGHT_CLASS = "h-44";

/**
 * A season card's content floor (Ben, 2026-09-10: same-size cards): tall enough for the champion
 * plus one placings line, whether or not a season has one. The card's `p-4` sits outside it, so
 * the placeholder below is the floor plus that padding.
 */
export const SEASON_CARD_MIN_HEIGHT_CLASS = "min-h-[7.5rem]";
export const SEASON_CARD_PLACEHOLDER_HEIGHT_CLASS = "h-38";
