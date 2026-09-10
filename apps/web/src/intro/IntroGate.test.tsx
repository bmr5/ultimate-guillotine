import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IntroGate } from "./IntroGate";

/**
 * The overlay itself is tested in `Intro.test.tsx`; here it is a stub with two buttons, so the
 * gate's phases can be driven by hand and the timeline never enters into it.
 */
vi.mock("./Intro", () => ({
  Intro: ({
    onReveal,
    onDone,
  }: {
    onReveal: () => void;
    onDone: () => void;
  }) => (
    <div data-testid="intro-stub">
      <button type="button" onClick={onReveal}>
        part
      </button>
      <button type="button" onClick={onDone}>
        finish
      </button>
    </div>
  ),
}));

function stubReducedMotion(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: matches && query.includes("prefers-reduced-motion"),
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
}

function gate(): HTMLElement {
  const element = document.querySelector("[data-intro]");
  if (!(element instanceof HTMLElement)) throw new Error("no gate");
  return element;
}

describe("IntroGate", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("skips the show entirely for a reader who asked for reduced motion", () => {
    stubReducedMotion(true);
    render(
      <IntroGate>
        <p>the board</p>
      </IntroGate>,
    );
    expect(gate()).toHaveAttribute("data-intro", "done");
    expect(screen.queryByTestId("intro-stub")).toBeNull();
    expect(screen.getByText("the board")).toBeInTheDocument();
  });

  it("holds the page as playing, lets it in as the curtain parts, and takes the overlay down when it is done", () => {
    stubReducedMotion(false);
    render(
      <IntroGate>
        <p>the board</p>
      </IntroGate>,
    );
    // The page is mounted underneath from the first render: its requests must not wait.
    expect(screen.getByText("the board")).toBeInTheDocument();
    expect(gate()).toHaveAttribute("data-intro", "playing");
    expect(screen.getByTestId("intro-stub")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "part" }));
    expect(gate()).toHaveAttribute("data-intro", "revealing");
    expect(screen.getByTestId("intro-stub")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "finish" }));
    expect(gate()).toHaveAttribute("data-intro", "done");
    expect(screen.queryByTestId("intro-stub")).toBeNull();
  });

  it("plays where there is no matchMedia to consult", () => {
    vi.stubGlobal("matchMedia", undefined);
    render(
      <IntroGate>
        <p>the board</p>
      </IntroGate>,
    );
    expect(gate()).toHaveAttribute("data-intro", "playing");
  });
});
