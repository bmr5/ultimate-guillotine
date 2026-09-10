/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { HistoryClient } from "./fetchers";
import {
  fetchRegisteredRevisions,
  fetchRegisteredTrades,
  fetchSeasonResults,
  fetchTradeCatalog,
} from "./fetchers";

interface Call {
  table: string;
  columns: string;
  order?: [string, boolean];
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

describe("fetchRegisteredRevisions", () => {
  it("reads three JSON paths out of terms and never the document itself", async () => {
    const { client, calls } = createFakeClient({ trade_revisions: [] });
    await fetchRegisteredRevisions(client);
    expect(calls[0].table).toBe("trade_revisions");
    expect(calls[0].columns).not.toMatch(/(^|,)\s*terms\s*(,|$)/);
    expect(calls[0].columns).not.toContain("evidence_excerpt");
    const paths = calls[0].columns
      .split(",")
      .map((column) => column.trim())
      .filter((column) => column.includes("terms"));
    expect(paths).toEqual([
      "kind:terms->>kind",
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

describe("fetchSeasonResults", () => {
  it("selects season results newest first", async () => {
    const { client, calls } = createFakeClient({ season_results: [] });
    await fetchSeasonResults(client);
    expect(calls[0].table).toBe("season_results");
    expect(calls[0].order).toEqual(["season", false]);
  });
});
