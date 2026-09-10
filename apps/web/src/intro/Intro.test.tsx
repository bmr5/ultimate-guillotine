import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Intro } from "./Intro";
import { INTRO_DONE_MS, INTRO_TIMELINE } from "./timeline";

/**
 * jsdom has no `document.fonts`, so `waitForFonts` resolves on a microtask and the show starts
 * on the first flush. What this file tests is the stage machine around the CSS: when the art
 * starts, when the curtain parts, when the overlay says it is finished, and that a tap or a key
 * cuts straight to the reveal.
 */
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function overlay(): HTMLElement {
  const element = document.querySelector("[data-intro-overlay]");
  if (!(element instanceof HTMLElement)) throw new Error("no overlay");
  return element;
}

describe("Intro", () => {
  const onReveal = vi.fn();
  const onDone = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    onReveal.mockClear();
    onDone.mockClear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is decorative: hidden from assistive technology", () => {
    render(<Intro onReveal={onReveal} onDone={onDone} />);
    expect(overlay()).toHaveAttribute("aria-hidden", "true");
  });

  it("holds the curtain until the font is in, then plays, parts, and finishes on the timeline", async () => {
    render(<Intro onReveal={onReveal} onDone={onDone} />);
    expect(overlay()).not.toHaveAttribute("data-playing");

    await flush();
    expect(overlay()).toHaveAttribute("data-playing");
    expect(overlay()).not.toHaveAttribute("data-revealing");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_TIMELINE.revealMs - 1);
    });
    expect(onReveal).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(overlay()).toHaveAttribute("data-revealing");
    expect(onReveal).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_TIMELINE.curtainMs);
    });
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("writes its timeline onto the element so the stylesheet cannot drift from it", () => {
    render(<Intro onReveal={onReveal} onDone={onDone} />);
    const style = overlay().style;
    expect(style.getPropertyValue("--intro-draw")).toBe(
      `${INTRO_TIMELINE.drawMs}ms`,
    );
    expect(style.getPropertyValue("--intro-lift")).toBe(
      `${INTRO_TIMELINE.liftMs}ms`,
    );
    expect(style.getPropertyValue("--intro-impact")).toBe(
      `${INTRO_TIMELINE.impactMs}ms`,
    );
    expect(style.getPropertyValue("--intro-curtain")).toBe(
      `${INTRO_TIMELINE.curtainMs}ms`,
    );
  });

  it("cuts to the reveal on a tap, and finishes once the curtain has cleared", async () => {
    render(<Intro onReveal={onReveal} onDone={onDone} />);
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });

    fireEvent.pointerDown(overlay());
    expect(overlay()).toHaveAttribute("data-revealing");
    expect(onReveal).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_TIMELINE.curtainMs - 1);
    });
    expect(onDone).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(onDone).toHaveBeenCalledTimes(1);

    // The scheduled reveal must not fire a second time after the skip.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_DONE_MS);
    });
    expect(onReveal).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("cuts to the reveal on a key press", async () => {
    render(<Intro onReveal={onReveal} onDone={onDone} />);
    await flush();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(overlay()).toHaveAttribute("data-revealing");
    expect(onReveal).toHaveBeenCalledTimes(1);
  });

  it("ignores a second skip while the curtain is already parting", async () => {
    render(<Intro onReveal={onReveal} onDone={onDone} />);
    await flush();
    fireEvent.pointerDown(overlay());
    fireEvent.pointerDown(overlay());
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onReveal).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_DONE_MS);
    });
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("drops every timer on unmount so nothing reports to a gate that is gone", async () => {
    const { unmount } = render(<Intro onReveal={onReveal} onDone={onDone} />);
    await flush();
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(INTRO_DONE_MS * 2);
    });
    expect(onReveal).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("carries the wordmark on both halves of the curtain, so the cut runs through it", () => {
    render(<Intro onReveal={onReveal} onDone={onDone} />);
    expect(screen.getAllByText("Guillotine")).toHaveLength(2);
    expect(screen.getAllByText("Ultimate")).toHaveLength(2);
  });
});
