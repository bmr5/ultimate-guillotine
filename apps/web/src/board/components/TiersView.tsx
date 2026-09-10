import { Card, CardContent } from "@/components/ui/card";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import { formatFaab } from "../derive/faab";
import { richestTeam, tierBlurb, type FaabTiers } from "../derive/tiers";
import { BOARD_GRID } from "../layout";
import { FaabCurveChart } from "./FaabCurveChart";

/** Three cards, richest tier first: the owner and the team, nothing else (Ben, 2026-09-10). */
export function TiersView({ tiers }: { tiers: FaabTiers }) {
  const richest = richestTeam(tiers);
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
                <p className="text-sm text-muted-foreground italic">
                  {tierBlurb(tier)}
                </p>
                <ul className="space-y-1 text-sm">
                  {tier.teams.map((team) => (
                    <li
                      key={team.teamId}
                      data-team={team.teamId}
                      className="flex items-baseline justify-between gap-3"
                    >
                      <span className="min-w-0 truncate">
                        <span className="font-medium text-foreground">
                          {team.ownerName}
                        </span>
                        {richest !== null && richest.teamId === team.teamId ? (
                          <span
                            data-crown
                            className="ml-1 rounded border border-primary/40 px-1 text-[0.6875rem] font-medium text-primary"
                            title="Richest team in the league"
                          >
                            richest
                          </span>
                        ) : null}
                        <span className="text-muted-foreground">{` · ${team.teamName}`}</span>
                      </span>
                      {/* Ben (2026-09-10): "put the teams FAAB $ amount!" */}
                      <span className="shrink-0 text-foreground tabular-nums">
                        {formatFaab(team.faabRemaining as number)}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
      <FaabCurveChart tiers={tiers} />
      <p className="text-xs text-muted-foreground">
        {`Split by ${tiers.method}.`}
        {tiers.unknown.length > 0
          ? ` ${tiers.unknown.length} ${tiers.unknown.length === 1 ? "team has" : "teams have"} no FAAB on file.`
          : ""}
      </p>
    </div>
  );
}
