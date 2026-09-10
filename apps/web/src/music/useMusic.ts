import { useCallback, useEffect, useRef, useState } from "react";

import { createMusicEngine, type MusicEngine } from "./engine";

/**
 * Where the reader's choice is remembered. The music is off until they turn it on — Ben, once
 * he had heard it on every load: "it's super annoying though. can you start it muted haha" — so
 * the only thing stored is the on, and absent means muted.
 */
export const MUSIC_KEY = "music";
export const MUSIC_ON = "on";

/**
 * The gestures that may start the tune. The browser only lets audio begin from a user gesture,
 * and these are the ones it counts: a released tap or click on anything, or a key. A scroll is
 * not one, on purpose — the reader who only scrolls the board has not asked for anything yet.
 */
export const GESTURE_EVENTS = ["pointerup", "keydown"] as const;

/**
 * The mute button carries this attribute, and gestures on it are never the ones that start the
 * tune: a reader whose first act on the site is to press mute would otherwise hear a blip of
 * music between the press and the mute.
 */
export const TOGGLE_ATTRIBUTE = "data-music-toggle";

export function readMuted(): boolean {
  try {
    return window.localStorage.getItem(MUSIC_KEY) !== MUSIC_ON;
  } catch {
    return true;
  }
}

export function writeMuted(muted: boolean): void {
  try {
    if (muted) {
      window.localStorage.removeItem(MUSIC_KEY);
    } else {
      window.localStorage.setItem(MUSIC_KEY, MUSIC_ON);
    }
  } catch {
    // Storage refused — a private window, or a browser told to keep none. The choice still
    // holds for this visit; it is only not remembered for the next.
  }
}

function isOnToggle(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    target.closest(`[${TOGGLE_ATTRIBUTE}]`) !== null
  );
}

/**
 * The music preference and the one control over it.
 *
 * The music is muted until the reader turns it on, and the on is remembered in local storage
 * for their next visit. Because the browser will not start audio on its own, a remembered on
 * waits for the reader's first tap or key anywhere on the page and starts then; while the
 * music is wanted, every gesture asks the engine to play, which is a no-op once it is playing
 * and the retry the autoplay rule needs when the browser did not honour the first one.
 *
 * Unmuting starts the tune from inside the click handler itself rather than from an effect,
 * because Safari only counts a resume made synchronously within the gesture.
 */
export function useMusic(): { muted: boolean; toggle: () => void } {
  const [muted, setMuted] = useState(readMuted);
  const engineRef = useRef<MusicEngine | null>(null);
  const engine = useCallback(
    () => (engineRef.current ??= createMusicEngine()),
    [],
  );

  useEffect(() => {
    if (muted) return;
    const controller = new AbortController();
    const onGesture = (event: Event) => {
      if (isOnToggle(event.target)) return;
      engine().play();
    };
    for (const type of GESTURE_EVENTS) {
      window.addEventListener(type, onGesture, {
        passive: true,
        signal: controller.signal,
      });
    }
    return () => controller.abort();
  }, [muted, engine]);

  useEffect(
    () => () => {
      engineRef.current?.dispose();
      engineRef.current = null;
    },
    [],
  );

  const toggle = useCallback(() => {
    const next = !muted;
    setMuted(next);
    writeMuted(next);
    if (next) {
      engine().pause();
    } else {
      engine().play();
    }
  }, [muted, engine]);

  return { muted, toggle };
}
