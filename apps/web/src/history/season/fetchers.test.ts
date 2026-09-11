/** @vitest-environment node */
import { PostgrestClient } from "@supabase/postgrest-js";
import { describe, expect, it, vi } from "vitest";

import { fetchEventPlayers, fetchSeasonArchive } from "./fetchers";
import { eventRecord, weekRecord } from "./fixtures.test-support";
import type { ArchiveDatabase } from "./types";

function clientWith(respond: (url: URL) => Response) {
  const fetch = vi.fn(async (input: RequestInfo | URL) =>
    respond(new URL(String(input))),
  );
  return {
    client: new PostgrestClient<ArchiveDatabase>(
      "https://archive.invalid/rest/v1",
      { fetch },
    ),
    fetch,
  };
}
const json = (data: unknown) =>
  new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });

describe("archive reads", () => {
  it("scopes to 2026 and does not query any historical event table when empty", async () => {
    const { client, fetch } = clientWith((url) => {
      expect(url.pathname).toContain("season_history_current_weeks");
      expect(url.searchParams.get("season")).toBe("eq.2026");
      return json([]);
    });
    expect(await fetchSeasonArchive(client)).toEqual({ weeks: [], events: [] });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("uses current revision IDs and paginates events without truncating", async () => {
    const { client } = clientWith((url) => {
      if (url.pathname.endsWith("season_history_current_weeks"))
        return json([weekRecord()]);
      expect(url.pathname).toContain("season_history_current_events");
      expect(url.searchParams.get("week_revision_id")).toBe("in.(1)");
      const offset = Number(url.searchParams.get("offset"));
      return json(
        offset === 0
          ? Array.from({ length: 500 }, (_, i) => eventRecord(i + 1))
          : [eventRecord(501)],
      );
    });
    expect((await fetchSeasonArchive(client)).events).toHaveLength(501);
  });
  it("fails the whole read if events fail instead of returning zero cuts", async () => {
    const { client } = clientWith((url) =>
      url.pathname.endsWith("season_history_current_weeks")
        ? json([weekRecord()])
        : new Response(JSON.stringify({ message: "unavailable" }), {
            status: 400,
          }),
    );
    await expect(fetchSeasonArchive(client)).rejects.toThrow(
      "Could not load the weekly events",
    );
  });
  it("requests the specific saved roster, never today's holdings", async () => {
    const { client } = clientWith((url) => {
      expect(url.pathname).toContain("season_history_current_players");
      expect(url.searchParams.get("snapshot_id")).toBe("eq.123");
      return json([]);
    });
    expect(await fetchEventPlayers(client, 123)).toEqual([]);
  });
});
