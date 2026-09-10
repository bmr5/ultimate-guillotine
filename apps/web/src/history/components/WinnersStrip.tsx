import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import { seasonPlacingLabel } from "../derive/ownerLabel";
import type { SeasonResult } from "../types";

/** Every season's champion in one scannable column — the answer most people open `/history` for. */
export function WinnersStrip({ seasons }: { seasons: SeasonResult[] }) {
  return (
    <ul
      aria-label="Winners"
      className={`divide-y rounded-xl border bg-card text-sm ${REVEAL_CLASS}`}
      // The first thing on the page to settle; the season cards follow it down.
      style={revealStyle(0)}
    >
      {seasons.map((season) => (
        <li key={season.season} className="flex justify-between px-3 py-1.5">
          <span className="text-base figures text-muted-foreground">
            {season.season}
          </span>
          {/* The same call the season card makes, so a season cannot be a former manager
              in one place and not recorded in the other. */}
          <span className="font-medium">
            {seasonPlacingLabel(season.championLabel, season.championMemberId)}
          </span>
        </li>
      ))}
    </ul>
  );
}
