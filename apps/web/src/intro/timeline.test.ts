/**
 * @vitest-environment node
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FONT_WAIT_MS,
  INTRO_DONE_MS,
  INTRO_TIMELINE,
  waitForFonts,
} from "./timeline";

describe("INTRO_TIMELINE", () => {
  it("runs in the order the eye needs: draw, lift, fall, impact, curtain", () => {
    const { drawMs, liftMs, impactMs, revealMs } = INTRO_TIMELINE;
    expect(drawMs).toBeLessThanOrEqual(liftMs);
    expect(liftMs).toBeLessThan(impactMs);
    expect(impactMs).toBeLessThan(revealMs);
  });

  it("is done once the curtain has cleared the viewport", () => {
    expect(INTRO_DONE_MS).toBe(
      INTRO_TIMELINE.revealMs + INTRO_TIMELINE.curtainMs,
    );
  });

  it("stays short: a member on a phone is here for the score, not the show", () => {
    expect(INTRO_DONE_MS).toBeLessThanOrEqual(2200);
    expect(FONT_WAIT_MS).toBeLessThanOrEqual(800);
  });
});

describe("waitForFonts", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("resolves at once where the Font Loading API does not exist", async () => {
    vi.stubGlobal("document", {});
    await expect(waitForFonts(FONT_WAIT_MS)).resolves.toBeUndefined();
  });

  it("resolves as soon as Archivo has loaded", async () => {
    vi.useFakeTimers();
    let resolveLoad: (faces: unknown[]) => void = () => undefined;
    const load = vi.fn(
      () =>
        new Promise<unknown[]>((resolve) => {
          resolveLoad = resolve;
        }),
    );
    vi.stubGlobal("document", { fonts: { load } });
    let settled = false;
    const waiting = waitForFonts(FONT_WAIT_MS).then(() => {
      settled = true;
    });
    expect(load).toHaveBeenCalledWith(expect.stringContaining("Archivo"));
    resolveLoad([]);
    await waiting;
    expect(settled).toBe(true);
  });

  it("gives up waiting after the cap so a slow font never stalls the show", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("document", {
      fonts: { load: () => new Promise<unknown[]>(() => undefined) },
    });
    let settled = false;
    const waiting = waitForFonts(FONT_WAIT_MS).then(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(FONT_WAIT_MS - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await waiting;
    expect(settled).toBe(true);
  });

  it("treats a font that fails to load like one that took too long", async () => {
    vi.stubGlobal("document", {
      fonts: { load: () => Promise.reject(new Error("no such face")) },
    });
    await expect(waitForFonts(FONT_WAIT_MS)).resolves.toBeUndefined();
  });
});
