import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { formatUpdatedAt } from "@/board/derive/time";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { StatsStrip } from "@/history/components/StatsStrip";
import { TradeCard } from "@/history/components/TradeCard";
import { TradeFilterBar } from "@/history/components/TradeFilterBar";
import {
  filterTrades,
  positionOptions,
  seasonOptions,
  typeOptions,
} from "@/history/derive/filter";
import { tradeStats } from "@/history/derive/stats";
import { parseNumberParam, type TradeFilters } from "@/history/types";
import { useTradeCatalog } from "@/history/useTradeCatalog";

export function TradesPage() {
  const [params, setParams] = useSearchParams();
  const { trades, replacedByBackfill, loadedAt, members, isPending, errors } =
    useTradeCatalog();

  // Memoised on `params` rather than rebuilt each render: `filters` is a dependency of the
  // filter memo below, and `react-hooks/exhaustive-deps` is a warning that `--max-warnings 0`
  // turns into a failed lint.
  const filters: TradeFilters = useMemo(
    () => ({
      season: parseNumberParam(params.get("season")),
      type: params.get("type"),
      position: params.get("pos"),
      memberId: parseNumberParam(params.get("owner")),
      search: params.get("q") ?? "",
    }),
    [params],
  );

  function change(next: Partial<TradeFilters>) {
    const updated = new URLSearchParams(params);
    const mapping: [keyof TradeFilters, string][] = [
      ["season", "season"],
      ["type", "type"],
      ["position", "pos"],
      ["memberId", "owner"],
      ["search", "q"],
    ];
    for (const [key, param] of mapping) {
      if (!(key in next)) continue;
      const value = next[key];
      if (value === null || value === "") updated.delete(param);
      else updated.set(param, String(value));
    }
    setParams(updated, { replace: true });
  }

  const visible = useMemo(
    () => filterTrades(trades, filters),
    [trades, filters],
  );
  const stats = useMemo(() => tradeStats(visible), [visible]);
  const memberIds = useMemo(
    () => [
      ...new Set(
        trades.flatMap((trade) => trade.parties.map((p) => p.memberId)),
      ),
    ],
    [trades],
  );

  return (
    <section className="space-y-3">
      <TradeFilterBar
        filters={filters}
        seasons={seasonOptions(trades)}
        types={typeOptions(trades)}
        positions={positionOptions(trades)}
        members={members}
        memberIds={memberIds}
        onChange={change}
        onClear={() => setParams(new URLSearchParams(), { replace: true })}
      />
      <StatsStrip stats={stats} replacedByBackfill={replacedByBackfill} />

      {errors.map((error) => (
        <Alert key={error.message} variant="destructive">
          <AlertTitle>Could not load part of the catalog</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ))}

      {isPending && (
        <div className="space-y-2">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-20 w-full" />
          ))}
        </div>
      )}

      {!isPending && trades.length === 0 && (
        <p className="rounded-md border bg-card p-4 text-sm">
          No trades loaded yet.
        </p>
      )}
      {!isPending && trades.length > 0 && visible.length === 0 && (
        <p className="rounded-md border bg-card p-4 text-sm">
          No trades match these filters.
        </p>
      )}

      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {visible.map((trade) => (
          <TradeCard key={trade.key} trade={trade} />
        ))}
      </ul>

      {loadedAt !== null && (
        // `formatUpdatedAt` needs the instant it is comparing against and already writes its
        // own "Updated" prefix, so the line is its output alone rather than "Loaded " + it.
        <p className="text-xs text-muted-foreground">
          {formatUpdatedAt(loadedAt, Date.now())}
        </p>
      )}
    </section>
  );
}
