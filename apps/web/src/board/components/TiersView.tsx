import { Card, CardContent } from "@/components/ui/card";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import { formatFaab } from "../derive/faab";
import type { FaabTiers } from "../derive/tiers";
import { BOARD_GRID } from "../layout";

/** Three cards, richest tier first: the owner and the team, nothing else (Ben, 2026-09-10). */
export function TiersView({ tiers }: { tiers: FaabTiers }) {
  return (
    <div className="space-y-3">
      <ul className={BOARD_GRID} aria-label="FAAB tiers">
        {tiers.tiers.map((tier, index) => (
          // The header is place 0 in the board's cascade; the three tiers follow it down.
          <li
            key={tier.key}
            data-tier={tier.key}
            className={REVEAL_CLASS}
            style={revealStyle(index + 1)}
          >
            <Card className="h-full">
              <CardContent className="space-y-2 p-4">
                <p className="text-2xl leading-none figures">{tier.label}</p>
                <p className="text-xs text-muted-foreground">
                  {tier.min === null || tier.max === null
                    ? "Nobody here"
                    : tier.min === tier.max
                      ? `${formatFaab(tier.min)} FAAB · ${tier.teams.length} ${tier.teams.length === 1 ? "team" : "teams"}`
                      : `${formatFaab(tier.min)}–${formatFaab(tier.max)} FAAB · ${tier.teams.length} teams`}
                </p>
                <ul className="space-y-1 text-sm">
                  {tier.teams.map((team) => (
                    <li key={team.teamId} data-team={team.teamId}>
                      <span className="font-medium text-foreground">
                        {team.ownerName}
                      </span>
                      <span className="text-muted-foreground">{` · ${team.teamName}`}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        {`Split by ${tiers.method}.`}
        {tiers.unknown.length > 0
          ? ` ${tiers.unknown.length} ${tiers.unknown.length === 1 ? "team has" : "teams have"} no FAAB on file.`
          : ""}
      </p>
    </div>
  );
}
