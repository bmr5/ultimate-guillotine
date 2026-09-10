import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import type { TradeStats } from "../derive/stats";

/** The strip's place in the trades page's cascade: right after the filter bar. */
const AFTER_FILTER_BAR = 1;

export function StatsStrip({
  stats,
  replacedByBackfill,
}: {
  stats: TradeStats;
  replacedByBackfill: number;
}) {
  // Two cells. "FAAB moved" went with the card's FAAB badge (Ben, 2026-09-09: the number is
  // not useful given how dynamic the deals are) and "Most traded" went the day after, by the
  // same ruling: the assets are stored as words now, not parsed, so a position count is not
  // a number the page can stand behind.
  const cells: [string, string][] = [
    ["Trades", String(stats.tradeCount)],
    ["Seasons", String(stats.seasonCount)],
  ];
  return (
    <div className={REVEAL_CLASS} style={revealStyle(AFTER_FILTER_BAR)}>
      <dl className="grid grid-cols-2 gap-2 rounded-xl border bg-card p-3 text-center">
        {cells.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-2xl leading-none figures">{value}</dd>
          </div>
        ))}
      </dl>
      {replacedByBackfill > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          {replacedByBackfill} earlier catalog{" "}
          {replacedByBackfill === 1 ? "reading" : "readings"} replaced by
          registered trades
        </p>
      )}
    </div>
  );
}
