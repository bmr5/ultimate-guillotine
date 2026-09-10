/**
 * @vitest-environment node
 */
import { afterEach, describe, expect, it, vi } from "vitest";

const URL_ = "https://abcdefgh.supabase.co";
const KEY = "anon-key-for-tests";

/**
 * Imported inside each test so the module evaluates against the stubbed env. Neither client
 * touches the network on construction — Realtime only opens its socket on `connect()`, which
 * the first `channel().subscribe()` triggers — so the real constructors are safe to run here.
 */
async function loadClient(url = URL_) {
  vi.stubEnv("VITE_SUPABASE_URL", url);
  vi.stubEnv("VITE_SUPABASE_ANON_KEY", KEY);
  vi.resetModules();
  return import("./supabaseClient");
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("supabaseClient", () => {
  it("points PostgREST at rest/v1 with the anon key as both apikey and bearer", async () => {
    const { postgrest } = await loadClient();
    expect(postgrest.url).toBe(`${URL_}/rest/v1`);
    expect(postgrest.schemaName).toBe("public");
    // The two headers supabase-js's fetch wrapper adds with no session: PostgREST reads the
    // role off the bearer, so dropping it would turn every select into a 401.
    expect(postgrest.headers.get("apikey")).toBe(KEY);
    expect(postgrest.headers.get("Authorization")).toBe(`Bearer ${KEY}`);
  });

  it("points Realtime at the websocket realtime/v1 endpoint with the anon key", async () => {
    const { realtime } = await loadClient();
    expect(realtime.endPoint).toBe(
      `wss://abcdefgh.supabase.co/realtime/v1/websocket`,
    );
    expect(realtime.apiKey).toBe(KEY);
    // Realtime evaluates RLS for postgres_changes against the token in the join payload, and
    // the umbrella client sends the anon key there when nobody is signed in.
    await expect(realtime.accessToken?.()).resolves.toBe(KEY);
  });

  it("tolerates a trailing slash on the project URL", async () => {
    const { postgrest, realtime } = await loadClient(`${URL_}/`);
    expect(postgrest.url).toBe(`${URL_}/rest/v1`);
    expect(realtime.endPoint).toBe(
      `wss://abcdefgh.supabase.co/realtime/v1/websocket`,
    );
  });
});
