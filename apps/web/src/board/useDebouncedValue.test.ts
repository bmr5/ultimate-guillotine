import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the initial value straight away", () => {
    const { result } = renderHook(() => useDebouncedValue("zo", 200));
    expect(result.current).toBe("zo");
  });

  it("holds the old value until the delay elapses", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 200),
      { initialProps: { value: "z" } },
    );

    rerender({ value: "zo" });
    expect(result.current).toBe("z");

    act(() => {
      vi.advanceTimersByTime(199);
    });
    expect(result.current).toBe("z");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe("zo");
  });

  it("only settles on the last value of a run of keystrokes", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 200),
      { initialProps: { value: "z" } },
    );

    for (const value of ["zo", "zod", "zodi"]) {
      rerender({ value });
      act(() => {
        vi.advanceTimersByTime(150);
      });
      expect(result.current).toBe("z");
    }

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(result.current).toBe("zodi");
  });
});
