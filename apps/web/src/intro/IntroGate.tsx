import { useCallback, useState, type ReactNode } from "react";

import { Intro } from "./Intro";

/**
 * Where the opening is: `playing` while the curtain is up, `revealing` from the moment it starts
 * to part, `done` once it has cleared and the overlay is gone. `globals.css` reads it off the
 * gate's `data-intro` attribute to hold every `.reveal` entrance paused until the curtain parts.
 */
export type IntroPhase = "playing" | "revealing" | "done";

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Mounts the app and, over it, the opening curtain — and never the other way round: the page
 * renders underneath from the first frame, so the font, the route chunk and the first data all
 * load while the show plays rather than after it.
 *
 * A reader who asked for reduced motion gets no curtain at all (the phase starts at `done`), the
 * same call `Sky` makes about the aurora. The wrapper is `display: contents` so it adds no box
 * to the layout; it exists to carry the phase where the stylesheet can see it.
 */
export function IntroGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<IntroPhase>(() =>
    prefersReducedMotion() ? "done" : "playing",
  );
  const handleReveal = useCallback(() => setPhase("revealing"), []);
  const handleDone = useCallback(() => setPhase("done"), []);

  return (
    <div data-intro={phase} className="contents">
      {children}
      {phase === "done" ? null : (
        <Intro onReveal={handleReveal} onDone={handleDone} />
      )}
    </div>
  );
}
