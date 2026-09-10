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
      {replacedByBackfill > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          {replacedByBackfill} earlier catalog readings replaced by registered
          trades
        </p>
      )}
    </div>
  );
}
