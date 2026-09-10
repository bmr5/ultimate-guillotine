import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Sky } from "./Sky";

/**
 * The renderer is mocked whole: vgpu needs a real GPU, and what this file tests is the gate in
 * front of it — when the canvas mounts at all, and that it stays invisible until `ready`.
 */
const dispose = vi.fn();
let resolveReady: () => void = () => undefined;
const createRenderer = vi.fn(() => ({
  ready: new Promise<void>((resolve) => {
    resolveReady = resolve;
  }),
  getState: () => ({
    preference: "auto",
    effective: "high",
    reason: "initial",
  }),
  subscribe: () => () => undefined,
  setPreference: () => Promise.resolve(),
  dispose,
}));
vi.mock("./renderer", () => ({ createRenderer }));

function stubEnvironment({
  gpu,
  reducedMotion,
}: {
  gpu: boolean;
  reducedMotion: boolean;
}) {
  if (gpu) {
    Object.defineProperty(navigator, "gpu", { value: {}, configurable: true });
  } else {
    delete (navigator as { gpu?: unknown }).gpu;
  }
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: reducedMotion && query.includes("prefers-reduced-motion"),
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("Sky", () => {
  beforeEach(() => {
    dispose.mockClear();
    createRenderer.mockClear();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    delete (navigator as { gpu?: unknown }).gpu;
  });

  it("renders nothing without WebGPU, leaving the body's wash", () => {
    stubEnvironment({ gpu: false, reducedMotion: false });
    const { container } = render(<Sky />);
    expect(container.querySelector("canvas")).toBeNull();
    expect(createRenderer).not.toHaveBeenCalled();
  });

  it("renders nothing when the reader asked for reduced motion", () => {
    stubEnvironment({ gpu: true, reducedMotion: true });
    const { container } = render(<Sky />);
    expect(container.querySelector("canvas")).toBeNull();
    expect(createRenderer).not.toHaveBeenCalled();
  });

  it("keeps the canvas invisible until the first frame is on screen, then disposes on unmount", async () => {
    stubEnvironment({ gpu: true, reducedMotion: false });
    const { container, unmount } = render(<Sky />);
    await flush();
    const canvas = container.querySelector("canvas");
    expect(canvas).not.toBeNull();
    expect(canvas).toHaveAttribute("aria-hidden", "true");
    expect(canvas?.className).toContain("opacity-0");
    expect(createRenderer).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveReady();
    });
    expect(canvas?.className).toContain("opacity-100");

    unmount();
    expect(dispose).toHaveBeenCalledTimes(1);
  });
});
