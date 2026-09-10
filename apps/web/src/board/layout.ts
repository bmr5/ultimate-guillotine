/**
 * The board's own measurements, in one place because two files render them.
 *
 * Ben, 2026-09-10: "make the board always one column. I find it confusing to have 2 cols on a
 * 1-18 ranked board." A rank only reads down a single column — side by side, rank 2 sits level
 * with rank 1 and the ordering has to be reconstructed by eye — so the board holds one column
 * at every width and gives up the horizontal density instead.
 */

/** One column at every breakpoint; no `sm:`/`lg:` column class may come back. */
export const BOARD_GRID = "grid grid-cols-1 gap-3";

/**
 * The measure the header, the lists and the skeleton all share.
 *
 * Narrower than the shell's `max-w-6xl` (see `app/layout.tsx`): a single column of full-width
 * cards across a desktop monitor is a long line to read a name off. Applied to the board's
 * `<main>` rather than to each list, so the header's controls stay flush with the cards below.
 */
export const BOARD_WIDTH = "mx-auto w-full max-w-2xl";
