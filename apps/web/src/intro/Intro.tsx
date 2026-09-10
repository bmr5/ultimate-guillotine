import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { FONT_WAIT_MS, INTRO_TIMELINE, waitForFonts } from "./timeline";

/**
 * Where each spark flies from the cut, in stage units (see `--u` in `intro.css`). Mostly up and
 * out, the way sparks come off steel on stone; the two low ones land on the bottom half of the
 * curtain, which is the only half that can show them.
 */
const SPARKS: readonly { sx: number; sy: number }[] = [
  { sx: -74, sy: -48 },
  { sx: -32, sy: -72 },
  { sx: 24, sy: -66 },
  { sx: 70, sy: -40 },
  { sx: -54, sy: 36 },
  { sx: 50, sy: 44 },
];

/** The two lines of the wordmark; the cut runs through the second. */
const WORD_SMALL = "Ultimate";
const WORD = "Guillotine";

interface IntroProps {
  /** The curtain has begun to part: the page beneath may start its own entrance now. */
  onReveal: () => void;
  /** The curtain has cleared the viewport; the overlay can be taken down. */
  onDone: () => void;
}

/**
 * One half of the curtain's picture: the frame, the wordmark, the blade and the sparks, drawn in
 * full on both halves. Each half is `overflow: hidden` and anchors the same picture so that the
 * cut line (`y = 300` of the 480-unit stage) sits exactly on its seam — the top half shows
 * everything above the cut, the bottom half everything below — and the two read as one image
 * until they part. Which is the whole trick: the bottom half's copy of the word is the severed
 * half, and it falls on its own before the curtain does.
 */
function Curtain() {
  const steelId = useId();
  return (
    <>
      <div className="intro-anchor">
        <div className="intro-stage">
          <span className="intro-crossbar" />
          <span className="intro-upright intro-upright-left" />
          <span className="intro-upright intro-upright-right" />
          <span className="intro-base" />
          {/* The blade is animated on this wrapper, not on the SVG: a transformed div is a
              compositor layer, and a shader compiling for the sky behind the curtain cannot
              make it stutter mid-fall. It is drawn before the wordmark so that, landed, it sits
              behind the word's top half rather than hiding it: the cut has to be seen. */}
          <div className="intro-blade">
            <svg viewBox="0 0 460 88" aria-hidden="true">
              <defs>
                {/* Night steel: dark enough that the ink of the word reads over it, and lit
                    only where it was ground — the bevel and the edge below. */}
                <linearGradient id={steelId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#555b6e" />
                  <stop offset="0.6" stopColor="#343948" />
                  <stop offset="1" stopColor="#20242f" />
                </linearGradient>
              </defs>
              {/* The mouton: the weight that carries the blade down. */}
              <rect
                x="0"
                y="0"
                width="460"
                height="28"
                rx="2"
                className="intro-mouton"
              />
              {/* The blade, its edge ground on the diagonal with the low corner to the left. */}
              <polygon
                points="0,28 460,28 460,68 0,88"
                fill={`url(#${steelId})`}
              />
              {/* The bevel: the strip above the edge that was sharpened brightest. */}
              <polygon
                points="0,79 460,59 460,68 0,88"
                className="intro-bevel"
              />
              <line
                x1="0"
                y1="88"
                x2="460"
                y2="68"
                className="intro-edge-glow"
              />
              <line x1="0" y1="88" x2="460" y2="68" className="intro-edge" />
            </svg>
          </div>
          <span className="intro-word-small figures">{WORD_SMALL}</span>
          <span className="intro-word figures">{WORD}</span>
          {SPARKS.map((spark, index) => (
            <span
              key={index}
              className="intro-spark"
              style={
                {
                  "--sx": spark.sx,
                  "--sy": spark.sy,
                  // Turned to face the way it flies, so the streak reads as motion.
                  "--angle": `${Math.atan2(spark.sy, spark.sx)}rad`,
                } as CSSProperties
              }
            />
          ))}
        </div>
      </div>
      <span className="intro-flash" />
    </>
  );
}

/**
 * The opening: a curtain in the sky's own color, a guillotine drawn on it, and the league's name
 * on the block. The blade falls, severs the word, and the curtain parts along the cut with the
 * top half hoisted away and the bottom half dropping — the page is what was underneath.
 *
 * Ben, 2026-09-10: "when the site loads let's have a fun load in animation. something guillotine
 * themed." It is also the loading screen: the page mounts beneath it from the first render, so
 * the font, the route's chunk and the first Supabase reads all ride under the curtain, and it
 * never waits for any of them beyond the font's short cap. A tap or a key cuts straight to the
 * reveal.
 *
 * Decorative throughout: `aria-hidden`, no focusable content, and never mounted at all for a
 * reader who asked for reduced motion (`IntroGate` decides that). The art is all CSS, keyed off
 * `data-playing` and `data-revealing` here and timed by the custom properties this element
 * carries, so `INTRO_TIMELINE` is the single source of every delay.
 */
export function Intro({ onReveal, onDone }: IntroProps) {
  const [playing, setPlaying] = useState(false);
  const [revealing, setRevealing] = useState(false);

  // The latest callbacks, so a timer set on mount reports to whatever the gate handed us last.
  const callbacks = useRef({ onReveal, onDone });
  useEffect(() => {
    callbacks.current = { onReveal, onDone };
  }, [onReveal, onDone]);

  /**
   * Whether the curtain has already been told to part. A ref rather than the state above
   * because the skip handlers and the scheduled reveal can all fire in the same tick, and only
   * the first may count.
   */
  const revealed = useRef(false);
  const doneTimer = useRef<number | null>(null);

  const reveal = useCallback(() => {
    if (revealed.current) return;
    revealed.current = true;
    setRevealing(true);
    callbacks.current.onReveal();
    doneTimer.current = window.setTimeout(() => {
      doneTimer.current = null;
      callbacks.current.onDone();
    }, INTRO_TIMELINE.curtainMs);
  }, []);

  // The curtain is up from the first paint; the show starts once the wordmark's face is in.
  useEffect(() => {
    let cancelled = false;
    void waitForFonts(FONT_WAIT_MS).then(() => {
      if (!cancelled) setPlaying(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!playing) return;
    const timer = window.setTimeout(reveal, INTRO_TIMELINE.revealMs);
    return () => window.clearTimeout(timer);
  }, [playing, reveal]);

  // Any key skips: a reader reaching for the page has no interest in the show.
  useEffect(() => {
    window.addEventListener("keydown", reveal);
    return () => window.removeEventListener("keydown", reveal);
  }, [reveal]);

  useEffect(
    () => () => {
      if (doneTimer.current !== null) window.clearTimeout(doneTimer.current);
    },
    [],
  );

  const timeline = {
    "--intro-draw": `${INTRO_TIMELINE.drawMs}ms`,
    "--intro-lift": `${INTRO_TIMELINE.liftMs}ms`,
    "--intro-impact": `${INTRO_TIMELINE.impactMs}ms`,
    "--intro-reveal": `${INTRO_TIMELINE.revealMs}ms`,
    "--intro-curtain": `${INTRO_TIMELINE.curtainMs}ms`,
  } as CSSProperties;

  return (
    <div
      data-intro-overlay
      data-playing={playing || undefined}
      data-revealing={revealing || undefined}
      aria-hidden="true"
      className="intro"
      style={timeline}
      onPointerDown={reveal}
    >
      <div className="intro-panel intro-panel-top">
        <Curtain />
      </div>
      <div className="intro-panel intro-panel-bottom">
        <Curtain />
      </div>
    </div>
  );
}
