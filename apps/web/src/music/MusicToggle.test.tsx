import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MusicToggle, MUTE_LABEL } from "./MusicToggle";
import { MUSIC_KEY, MUSIC_ON } from "./useMusic";

/**
 * The engine is tested in `engine.test.ts`; here it is three spies, so what is under test is
 * the preference and the gestures: when the tune is asked to start, when to stop, and what is
 * remembered for next time.
 */
const { engine, created } = vi.hoisted(() => ({
  engine: { play: vi.fn(), pause: vi.fn(), dispose: vi.fn() },
  created: { count: 0 },
}));

vi.mock("./engine", () => ({
  createMusicEngine: () => {
    created.count += 1;
    return engine;
  },
}));

function muteButton(): HTMLElement {
  return screen.getByRole("button", { name: MUTE_LABEL });
}

/** The reader turned the music on last time, which is the only way it plays at all. */
function rememberOn() {
  window.localStorage.setItem(MUSIC_KEY, MUSIC_ON);
}

describe("MusicToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    created.count = 0;
  });

  it("starts muted: a pressed mute button, and no engine", () => {
    render(<MusicToggle />);
    expect(muteButton()).toHaveAttribute("aria-pressed", "true");
    expect(created.count).toBe(0);
  });

  it("stays quiet through taps and keys while muted", () => {
    render(<MusicToggle />);
    fireEvent.pointerUp(document.body);
    fireEvent.keyDown(document.body, { key: "Tab" });
    expect(engine.play).not.toHaveBeenCalled();
    expect(created.count).toBe(0);
  });

  it("unmutes on a click: starts the tune from the click itself, and remembers", () => {
    render(<MusicToggle />);
    fireEvent.click(muteButton());
    expect(engine.play).toHaveBeenCalledTimes(1);
    expect(muteButton()).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(MUSIC_KEY)).toBe(MUSIC_ON);
  });

  it("starts unmuted when the reader turned it on last time, but waits for a gesture", () => {
    rememberOn();
    render(<MusicToggle />);
    expect(muteButton()).toHaveAttribute("aria-pressed", "false");
    expect(engine.play).not.toHaveBeenCalled();
    fireEvent.pointerUp(document.body);
    expect(engine.play).toHaveBeenCalledTimes(1);
    expect(created.count).toBe(1);
  });

  it("counts a key press as the first gesture too", () => {
    rememberOn();
    render(<MusicToggle />);
    fireEvent.keyDown(document.body, { key: "Tab" });
    expect(engine.play).toHaveBeenCalledTimes(1);
  });

  it("does not start the tune from a gesture on the mute button itself", () => {
    rememberOn();
    render(<MusicToggle />);
    fireEvent.pointerUp(muteButton());
    fireEvent.keyDown(muteButton(), { key: "Enter" });
    expect(engine.play).not.toHaveBeenCalled();
  });

  it("mutes on a click: stops the tune, presses the button, and forgets the on", () => {
    rememberOn();
    render(<MusicToggle />);
    fireEvent.pointerUp(document.body);
    fireEvent.click(muteButton());
    expect(engine.pause).toHaveBeenCalledTimes(1);
    expect(muteButton()).toHaveAttribute("aria-pressed", "true");
    expect(window.localStorage.getItem(MUSIC_KEY)).toBeNull();

    // Muted means muted: a later tap on the page does not bring the tune back.
    fireEvent.pointerUp(document.body);
    expect(engine.play).toHaveBeenCalledTimes(1);
  });

  it("works where storage is refused", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage is disabled");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage is disabled");
    });
    render(<MusicToggle />);
    expect(muteButton()).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(muteButton());
    expect(muteButton()).toHaveAttribute("aria-pressed", "false");
    expect(engine.play).toHaveBeenCalledTimes(1);
  });

  it("lets the engine go when it unmounts", () => {
    rememberOn();
    const { unmount } = render(<MusicToggle />);
    fireEvent.pointerUp(document.body);
    unmount();
    expect(engine.dispose).toHaveBeenCalledTimes(1);
  });
});
