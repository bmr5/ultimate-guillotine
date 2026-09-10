/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { IN_CHUNK_SIZE } from "@/board/fetchers";

import type { HistoryClient } from "./fetchers";
import {
  fetchHistoryPlayers,
  fetchRegisteredRevisions,
  fetchRegisteredTrades,
  fetchSeasonResults,
  fetchTradeCatalog,
} from "./fetchers";

interface Call {
  table: string;
  columns: string;
  order?: [string, boolean];
  in?: [string, readonly string[]];
}

function createFakeClient(
  responses: Record<string, unknown[]>,
  error: { message: string } | null = null,
): {
  client: HistoryClient;
  calls: Call[];
} {
  const calls: Call[] = [];
  const client = {
    from(table: string) {
      const call: Call = { table, columns: "" };
      calls.push(call);
      const builder = {
        select(columns: string) {
          call.columns = columns;
          return builder;
        },
        order(column: string, options: { ascending: boolean }) {
          call.order = [column, options.ascending];
          return builder;
        },
        in(column: string, values: readonly string[]) {
          call.in = [column, values];
          return builder;
        },
        then(
          resolve: (value: {
            data: unknown[] | null;
            error: { message: string } | null;
          }) => unknown,
        ) {
          return Promise.resolve(
            error === null
              ? resolve({ data: responses[table] ?? [], error: null })
              : resolve({ data: null, error }),
          );
        },
      };
      return builder;
    },
  } as unknown as HistoryClient;
  return { client, calls };
}

describe("fetchTradeCatalog", () => {
  it("selects the catalog columns newest first", async () => {
    const { client, calls } = createFakeClient({ trade_catalog: [] });
    await fetchTradeCatalog(client);
    expect(calls[0].table).toBe("trade_catalog");
    expect(calls[0].columns).toContain("party_member_ids");
    expect(calls[0].columns).toContain("announcement");
    expect(calls[0].order).toEqual(["season", false]);
  });

  // Ben's ruling of 2026-09-09 took the FAAB total off the card and out of the stats strip, so
  // nothing reads the column any more — and this fetcher's rule is that it asks for exactly
  // what the page renders and no more.
  it("no longer asks for the analyst's FAAB total", async () => {
    const { client, calls } = createFakeClient({ trade_catalog: [] });
    await fetchTradeCatalog(client);
    expect(calls[0].columns).not.toContain("faab_total");
  });
});

describe("fetchRegisteredTrades", () => {
  it("never selects the whole terms document", async () => {
    // `terms` carries `evidence_excerpt` -- verbatim chat -- and Sleeper usernames.
    const { client, calls } = createFakeClient({ trades: [] });
    await fetchRegisteredTrades(client);
    expect(calls[0].columns).not.toMatch(/(^|,)\s*terms\s*(,|$)/);
    expect(calls[0].columns).not.toContain("evidence_excerpt");
    expect(calls[0].columns).toContain("seasons ( year )");
  });

  // The instant a registered card is dated by. `trade_revisions.created_at` would be the
  // current revision's and would move every time a deal is amended.
  it("asks for the instant the trade was recorded", async () => {
    const { client, calls } = createFakeClient({ trades: [] });
    await fetchRegisteredTrades(client);
    expect(calls[0].columns).toContain("created_at");
    expect(calls[0].columns).toContain("announced_at");
  });
});

describe("fetchRegisteredRevisions", () => {
  // Four paths now, not three: `evidence_excerpt` is requested on purpose, as `announcement`.
  // The assertion is still an equality against the whole list rather than a check that the new
  // path is present — the point of it is that no *fifth* path joins these by accident, and a
  // `toContain` would not notice one.
  it("reads four named JSON paths out of terms and never the document itself", async () => {
    const { client, calls } = createFakeClient({ trade_revisions: [] });
    await fetchRegisteredRevisions(client);
    expect(calls[0].table).toBe("trade_revisions");
    expect(calls[0].columns).not.toMatch(/(^|,)\s*terms\s*(,|$)/);
    const paths = calls[0].columns
      .split(",")
      .map((column) => column.trim())
      .filter((column) => column.includes("terms"));
    expect(paths).toEqual([
      "kind:terms->>kind",
      "announcement:terms->>evidence_excerpt",
      "parties:terms->parties",
      "assets:terms->assets",
    ]);
  });

  it("surfaces a query error as the table name and message only", async () => {
    const { client } = createFakeClient({}, { message: "boom" });
    await expect(fetchRegisteredRevisions(client)).rejects.toThrow(
      "trade_revisions: boom",
    );
  });
});

describe("fetchHistoryPlayers", () => {
  it("selects the id, the display name and the position, and nothing else", async () => {
    const { client, calls } = createFakeClient({ players: [] });
    await fetchHistoryPlayers(client, ["1"]);
    expect(calls[0].table).toBe("players");
    expect(calls[0].columns.split(",").map((column) => column.trim())).toEqual([
      "sleeper_player_id",
      "full_name",
      "position",
    ]);
    expect(calls[0].in).toEqual(["sleeper_player_id", ["1"]]);
  });

  it("chunks the id list rather than sending one oversized .in filter", async () => {
    // PostgREST puts `.in()` in the query string; past IN_CHUNK_SIZE the URL is the limit, and
    // an unfiltered read of the whole directory is worse — it can be silently row-capped.
    const ids = Array.from({ length: IN_CHUNK_SIZE + 1 }, (_, i) => String(i));
    const { client, calls } = createFakeClient({ players: [] });
    await fetchHistoryPlayers(client, ids);
    expect(calls).toHaveLength(2);
    expect(calls[0].in?.[1]).toHaveLength(IN_CHUNK_SIZE);
    expect(calls[1].in?.[1]).toEqual([String(IN_CHUNK_SIZE)]);
    expect(calls.every((call) => call.table === "players")).toBe(true);
  });

  it("asks for nothing at all when no trade references a player", async () => {
    const { client, calls } = createFakeClient({ players: [] });
    await expect(fetchHistoryPlayers(client, [])).resolves.toEqual([]);
    expect(calls).toHaveLength(0);
  });
});

describe("fetchSeasonResults", () => {
  it("selects season results newest first", async () => {
    const { client, calls } = createFakeClient({ season_results: [] });
    await fetchSeasonResults(client);
    expect(calls[0].table).toBe("season_results");
    expect(calls[0].order).toEqual(["season", false]);
  });
});
