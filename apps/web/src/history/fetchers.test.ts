/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { HistoryClient } from "./fetchers";
import {
  fetchRegisteredTrades,
  fetchSeasonResults,
  fetchTradeCatalog,
} from "./fetchers";

interface Call {
  table: string;
  columns: string;
  order?: [string, boolean];
}

function createFakeClient(responses: Record<string, unknown[]>): {
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
        then(resolve: (value: { data: unknown[]; error: null }) => unknown) {
          return Promise.resolve(
            resolve({ data: responses[table] ?? [], error: null }),
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
    expect(calls[0].order).toEqual(["season", false]);
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
});

describe("fetchSeasonResults", () => {
  it("selects season results newest first", async () => {
    const { client, calls } = createFakeClient({ season_results: [] });
    await fetchSeasonResults(client);
    expect(calls[0].table).toBe("season_results");
    expect(calls[0].order).toEqual(["season", false]);
  });
});
