import type { TradeStats } from "../derive/stats";

export function StatsStrip({
  stats,
  replacedByBackfill,
}: {
  stats: TradeStats;
  replacedByBackfill: number;
}) {
  // Three cells, not four: "FAAB moved" is gone with the card's FAAB badge, by Ben's ruling of
  // 2026-09-09 — "because of the dynamic nature of many deals it's most likely not useful to
  // include the FAAB number here". Its footnote went with it; it existed only to say which of
  // the two numbers counted a rescinded trade.
  const cells: [string, string][] = [
    ["Trades", String(stats.tradeCount)],
    ["Seasons", String(stats.seasonCount)],
    ["Most traded", stats.topPosition ?? "—"],
  ];
  return (
    <div>
      <dl className="grid grid-cols-3 gap-2 rounded-xl border bg-card p-3 text-center">
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
