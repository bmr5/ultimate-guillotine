/**
 * Every moment in the opening, in milliseconds from the start of play. The overlay writes these
 * onto its root element as custom properties (`--intro-lift` and so on), and `intro.css` reads
 * its delays from those, so the stylesheet and the stage machine in `Intro.tsx` cannot drift
 * apart: there is one timeline, and this is it.
 *
 *   0          the frame draws itself and the wordmark comes up
 *   liftMs     the blade lifts a hair — the rope pulled taut
 *   impactMs   the blade lands on the cut line; the word is severed
 *   revealMs   the curtain parts along the cut and the page is underneath
 *   + curtainMs  the curtain has cleared the viewport and the overlay is gone
 */
export const INTRO_TIMELINE = {
  /** By when the frame and the wordmark are fully on screen. */
  drawMs: 640,
  /** The blade's lift starts here; the fall follows straight out of it. */
  liftMs: 700,
  /** The blade lands. Shake, flash, sparks, and the severed half all key off this. */
  impactMs: 1050,
  /**
   * The curtain begins to part. Three hundred milliseconds after impact, so the severed half of
   * the word is seen to drop before the curtain does: parted any sooner, the two falls read as
   * one and the cut is lost.
   */
  revealMs: 1350,
  /** How long the curtain takes to clear the viewport once it parts. */
  curtainMs: 560,
} as const;

/** When the overlay reports itself finished: the curtain has cleared. */
export const INTRO_DONE_MS = INTRO_TIMELINE.revealMs + INTRO_TIMELINE.curtainMs;

/**
 * How long the curtain waits for Archivo before starting the show without it. The wordmark is
 * the whole picture, and a fallback face swapping to Archivo halfway through the drop would be
 * the one thing a reader noticed; but a font that is slow to arrive is not a reason to hold the
 * board back, and the curtain is already up while it waits.
 */
export const FONT_WAIT_MS = 700;

/**
 * The face the wordmark is set in, in the Font Loading API's shorthand. Asking for it is what
 * makes the browser fetch it now rather than on first paint of the text.
 */
const WORDMARK_FONT = '700 100px "Archivo Variable"';

/**
 * Resolves once Archivo is loaded, once it has failed to, or once `timeoutMs` has passed —
 * whichever comes first. Never rejects, and resolves at once where there is no Font Loading API
 * (jsdom, an old browser): the show then plays in whatever face is there.
 */
export function waitForFonts(timeoutMs: number): Promise<void> {
  const fonts = (globalThis as { document?: { fonts?: FontFaceSet } }).document
    ?.fonts;
  if (fonts === undefined) return Promise.resolve();
  const loaded = fonts.load(WORDMARK_FONT).then(
    () => undefined,
    () => undefined,
  );
  const capped = new Promise<void>((resolve) => {
    setTimeout(resolve, timeoutMs);
  });
  return Promise.race([loaded, capped]);
}
