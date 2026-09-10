import { useMemo } from "react";
import { useSearchParams } from "react-router";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { StatsStrip } from "@/history/components/StatsStrip";
import { TradeCard } from "@/history/components/TradeCard";
import { TradeFilterBar } from "@/history/components/TradeFilterBar";
import { TradesListSkeleton } from "@/history/components/TradesSkeleton";
import {
  filterTrades,
  positionOptions,
  seasonOptions,
  typeOptions,
} from "@/history/derive/filter";
import { ownerLabelFor } from "@/history/derive/ownerLabel";
import { tradeStats } from "@/history/derive/stats";
import { CARD_GRID } from "@/history/layout";
import { parseNumberParam, type TradeFilters } from "@/history/types";
import { useCurrentSeason } from "@/history/useCurrentSeason";
import { useTradeCatalog } from "@/history/useTradeCatalog";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

/**
 * Where the list sits in the page's cascade: the filter bar is place 0, the stats strip 1, and
 * the alerts, the placeholders, the empty states and the first card all follow as place 2.
 */
const BELOW_STRIP = 2;

/** The query params this page owns. Anything else in the URL is somebody else's and survives. */
const FILTER_PARAMS = ["season", "type", "pos", "owner", "q"] as const;

/**
 * The `season` value that means every season.
 *
 * The page opens on the current season (Ben's ruling of 2026-09-09), so an absent param is the
 * default and not "all": a reader who wants the whole catalog has to say so, and the All chip
 * writes this word rather than dropping the param, which would only put the default back.
 */
const SEASON_ALL = "all";

/** A season the URL names, `null` for every season, or `undefined` when the URL says nothing. */
function parseSeasonParam(value: string | null): number | null | undefined {
  if (value === SEASON_ALL) return null;
  return parseNumberParam(value) ?? undefined;
}

export function TradesPage() {
  const [params, setParams] = useSearchParams();
  const { trades, replacedByBackfill, members, isPending, errors } =
    useTradeCatalog();
  const currentSeason = useCurrentSeason();

  const seasonParam = parseSeasonParam(params.get("season"));
  /**
   * Only a URL that says nothing about the season waits on `nfl_state`: rendering every season
   * and narrowing to one a moment later would flash twenty years of trades past the reader.
   * Should the row fail to load, the page falls back to every season rather than to nothing.
   */
  const isSeasonPending = seasonParam === undefined && currentSeason.isPending;

  // Memoised on `params` rather than rebuilt each render: `filters` is a dependency of the
  // filter memo below, and `react-hooks/exhaustive-deps` is a warning that `--max-warnings 0`
  // turns into a failed lint.
  const filters: TradeFilters = useMemo(
    () => ({
      season: seasonParam === undefined ? currentSeason.season : seasonParam,
      type: params.get("type"),
      position: params.get("pos"),
      memberId: parseNumberParam(params.get("owner")),
      search: params.get("q") ?? "",
    }),
    [params, seasonParam, currentSeason.season],
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
      if (key === "season" && value === null) updated.set(param, SEASON_ALL);
      else if (value === null || value === "") updated.delete(param);
      else updated.set(param, String(value));
    }
    setParams(updated, { replace: true });
  }

  // Clear drops this page's five filters and nothing else: replacing the whole query string
  // would also throw away a param the router or a future feature put there.
  function clearFilters() {
    const updated = new URLSearchParams(params);
    for (const param of FILTER_PARAMS) updated.delete(param);
    setParams(updated, { replace: true });
  }

  const visible = useMemo(
    () => filterTrades(trades, filters),
    [trades, filters],
  );
  /**
   * The current season leads the chips whether or not it has a trade yet. Before the season's
   * first deal the catalog does not know the year exists, and the chip the page opened on
   * would otherwise be missing from its own filter bar.
   */
  const seasons = useMemo(() => {
    const options = seasonOptions(trades);
    if (currentSeason.season === null || options.includes(currentSeason.season))
      return options;
    return [currentSeason.season, ...options].sort((a, b) => b - a);
  }, [trades, currentSeason.season]);
  // Nothing to count until the season is known, or the strip would flash the whole catalog's
  // figures before settling on one season's.
  const stats = useMemo(
    () => tradeStats(isSeasonPending ? [] : visible),
    [isSeasonPending, visible],
  );
  // Only the owners this page can name, sorted by the label the `<option>` will carry.
  //
  // Ben's ruling: an unresolved party reads as a former manager, and the filter never lists
  // them. One option reading "Former manager" would stand for every unmapped party across
  // twenty years of catalog — picking it would gather strangers into one owner's view — and a
  // list of several identical options is worse still. They stay on the cards, where the wording
  // is about that one trade.
  //
  // Sorting by the label rather than by the member id: the id is an internal number, so
  // ordering by it puts the owners in what reads as no order at all. `localeCompare`, not `<`,
  // so the nicknames sort the way a reader expects rather than by code point.
  const memberIds = useMemo(() => {
    const named = new Map<number, string>();
    for (const trade of trades) {
      for (const party of trade.parties) {
        if (named.has(party.memberId)) continue;
        const label = ownerLabelFor(party.memberId, members);
        if (label !== null) named.set(party.memberId, label);
      }
    }
    return [...named.entries()]
      .sort(([, a], [, b]) => a.localeCompare(b))
      .map(([id]) => id);
  }, [trades, members]);

  return (
    <section className="space-y-3">
      <TradeFilterBar
        filters={filters}
        seasons={seasons}
        types={typeOptions(trades)}
        positions={positionOptions(trades)}
        members={members}
        memberIds={memberIds}
        onChange={change}
        onClear={clearFilters}
      />
      <StatsStrip stats={stats} replacedByBackfill={replacedByBackfill} />

      {/* Keyed by source, not by message: two sources that fail the same way — one outage, two
          identical messages — are two alerts with the same key otherwise, and React keeps only
          one of them. */}
      {errors.map(({ source, error }) => (
        <Alert
          key={source}
          variant="destructive"
          className={REVEAL_CLASS}
          style={revealStyle(BELOW_STRIP)}
        >
          <AlertTitle>Could not load {source.toLowerCase()}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ))}

      {(isPending || isSeasonPending) && (
        <TradesListSkeleton revealIndex={BELOW_STRIP} />
      )}

      {!isPending && !isSeasonPending && trades.length === 0 && (
        <p
          className={`rounded-xl border bg-card p-4 text-sm ${REVEAL_CLASS}`}
          style={revealStyle(BELOW_STRIP)}
        >
          No trades loaded yet.
        </p>
      )}
      {!isPending &&
        !isSeasonPending &&
        trades.length > 0 &&
        visible.length === 0 && (
          <div
            className={`space-y-2 rounded-xl border bg-card p-4 text-sm ${REVEAL_CLASS}`}
            style={revealStyle(BELOW_STRIP)}
          >
            <p>No trades match these filters.</p>
            <div className="flex flex-wrap gap-2">
              {/* Clear puts the defaults back, and the default season is the current one — so
                  on a season with no trades yet, Clear alone leads straight back here. */}
              {filters.season !== null && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => change({ season: null })}
                >
                  All seasons
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={clearFilters}
              >
                Clear filters
              </Button>
            </div>
          </div>
        )}

      {/* Named for the same reason `/history` names its season list: a screen reader announces
          an unlabelled list by its length alone, so "list, 12 items" on a page of filters and
          strips says nothing about which list it reached. */}
      <ul aria-label="Trades" className={CARD_GRID}>
        {!isSeasonPending &&
          visible.map((trade, index) => (
            <TradeCard
              key={trade.key}
              trade={trade}
              revealIndex={BELOW_STRIP + index}
            />
          ))}
      </ul>
    </section>
  );
}
