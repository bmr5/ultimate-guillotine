/**
 * @vitest-environment node
 */
import { describe, expect, it, vi } from "vitest";

/** Rest-typed so the third argument — the options object the assertion is about — is readable. */
const createClient = vi.hoisted(() =>
  vi.fn((...args: unknown[]) => ({ args })),
);
vi.mock("@supabase/supabase-js", () => ({ createClient }));

describe("supabaseClient", () => {
  it("holds no auth session, since the board is read-only and anonymous", async () => {
    // Imported inside the test so the module evaluates against the mock above.
    await import("./supabaseClient");
    // Left on, supabase-js writes an auth entry to localStorage, runs a refresh timer, and
    // parses every page load's hash for tokens this app never issues.
    expect(createClient.mock.calls[0][2]).toEqual({
      auth: {
        persistSession: false,
        autoRefreshToken: false,
        detectSessionInUrl: false,
      },
    });
  });
});
