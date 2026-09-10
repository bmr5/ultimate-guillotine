import { FORMER_MANAGER } from "../derive/ownerLabel";
import type { SeasonResult } from "../types";

/** Every season's champion in one scannable column — the answer most people open `/history` for. */
export function WinnersStrip({ seasons }: { seasons: SeasonResult[] }) {
  return (
    <ul
      aria-label="Winners"
      className="divide-y rounded-md border bg-card text-sm"
    >
      {seasons.map((season) => (
        <li key={season.season} className="flex justify-between px-3 py-1.5">
          <span className="text-muted-foreground">{season.season}</span>
          <span className="font-medium">
            {season.championLabel ?? FORMER_MANAGER}
          </span>
        </li>
      ))}
    </ul>
  );
}
