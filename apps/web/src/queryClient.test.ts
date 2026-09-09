/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { queryClient } from "./queryClient";

describe("queryClient", () => {
  it("retries a failed board query once, not the default three times", () => {
    // Every board query is a plain anonymous read: a second failure is a real failure, and the
    // default's backoff left a broken section spinning before the board could name it.
    expect(queryClient.getDefaultOptions().queries?.retry).toBe(1);
  });
});
