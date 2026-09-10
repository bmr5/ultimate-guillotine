import type { TradeStats } from "../derive/stats";

export function StatsStrip({
  stats,
  replacedByBackfill,
}: {
  stats: TradeStats;
  replacedByBackfill: number;
}) {
  const cells: [string, string][] = [
    ["Trades", String(stats.tradeCount)],
    ["Seasons", String(stats.seasonCount)],
    ["FAAB moved", String(stats.faabMoved)],
    ["Most traded", stats.topPosition ?? "—"],
  ];
  return (
    <div>
      <dl className="grid grid-cols-4 gap-2 rounded-md border bg-card p-2 text-center">
        {cells.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[11px] uppercase text-muted-foreground">
              {label}
            </dt>
            <dd className="text-sm font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      {/* `tradeCount` counts a rescinded trade — it happened — and `faabMoved` does not, so the
          two numbers in the strip are answering slightly different questions. Say which. */}
      <p className="mt-1 text-xs text-muted-foreground">
        FAAB moved excludes rescinded trades
      </p>
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
