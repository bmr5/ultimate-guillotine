import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import type { Renderer } from "./renderer";

/**
 * Same-origin copy of detect-gpu's benchmark tables, put in `public/` by the app's `predev` and
 * `prebuild` scripts. detect-gpu would otherwise fetch them from a CDN on every
 * visit; the tier signal is advisory, so a missing copy costs nothing but the signal.
 */
const BENCHMARKS_URL = "/gpu-benchmarks";

/**
 * Whether this browser gets the sky at all. Without WebGPU there is nothing to draw, and a
 * reader who asked for reduced motion gets the still wash `globals.css` paints on the body
 * rather than a slower aurora — the sky is the one thing on the page that moves on its own.
 */
function skySupported(): boolean {
  if (typeof navigator === "undefined" || !("gpu" in navigator)) return false;
  return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The aurora behind every page: the vgpu adaptive-quality example, fixed to the viewport at the
 * back of the stacking order. It starts on the High pipeline and drops once to Low if the GPU
 * tier, battery or frame rate asks (see `renderer.ts`). It is never a reason the board fails to
 * render: a renderer error is logged and the body's wash stays; the canvas fades in only once
 * the first frame is on screen. The renderer and vgpu behind it load in their own chunk from
 * the effect, after the board's own script, so the sky never delays the page it sits behind.
 */
export function Sky() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [supported] = useState(skySupported);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!supported || canvas === null) return;
    let cancelled = false;
    let renderer: Renderer | null = null;
    import("./renderer").then(
      ({ createRenderer }) => {
        if (cancelled) return;
        renderer = createRenderer({
          canvas,
          benchmarksUrl: BENCHMARKS_URL,
          onError: (error) => console.error("sky", error),
        });
        renderer.ready.then(
          () => {
            if (!cancelled) setReady(true);
          },
          // `ready` rejects when the GPU cannot be initialised; `onError` has already logged it.
          () => undefined,
        );
      },
      (error: unknown) => console.error("sky", error),
    );
    return () => {
      cancelled = true;
      renderer?.dispose();
    };
  }, [supported]);

  if (!supported) return null;

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      data-sky
      className={cn(
        "pointer-events-none fixed inset-0 -z-10 h-full w-full transition-opacity duration-1000",
        ready ? "opacity-100" : "opacity-0",
      )}
    />
  );
}
