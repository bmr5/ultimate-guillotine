import { Card, CardContent } from "@/components/ui/card";

import { FORMER_MANAGER, seasonPlacingLabel } from "../derive/ownerLabel";
import type { SeasonResult } from "../types";

/**
 * One of the placings that trail the champion, or `null` for one the season never recorded.
 *
 * The id decides whether the clause exists at all: a season with no runner-up on file says
 * nothing about a runner-up, which is why these are dropped rather than printed as "Not
 * recorded" the way the champion line is — the champion line is the card's subject and
 * always renders, these are an aside. But a placing the sheet *did* record and the directory
 * cannot name is a person, and dropping it would lose a fact the row is carrying; it reads
 * "Runner-up Former manager", the same as the champion line above it.
 */
function placingText(
  role: string,
  label: string | null,
  memberId: number | null,
): string | null {
  if (memberId === null) return null;
  return `${role} ${label ?? FORMER_MANAGER}`;
}

interface Props {
  season: SeasonResult;
}

export function SeasonCard({ season }: Props) {
  const runnerUps = [
    placingText(
      "Co-champion",
      season.coChampionLabel,
      season.coChampionMemberId,
    ),
    placingText("Runner-up", season.runnerUpLabel, season.runnerUpMemberId),
    placingText("Third", season.thirdLabel, season.thirdMemberId),
    season.teamCount !== null && `${season.teamCount} teams`,
  ].filter((part): part is string => Boolean(part));

  return (
    <li className="list-none">
      <Card>
        <CardContent className="space-y-2 p-4">
          <p className="text-xs text-muted-foreground">
            Champion {season.season}
          </p>
          <p className="text-3xl leading-none figures">
            {seasonPlacingLabel(season.championLabel, season.championMemberId)}
          </p>
          {runnerUps.length > 0 && (
            <p className="text-sm text-muted-foreground">
              {runnerUps.join(" · ")}
            </p>
          )}

          {/*
            Ben's ruling: the card carries no eliminations section. The rows are still loaded
            (`season.eliminations`); the card just does not read them.
          */}
          {season.notes !== null && (
            <p className="text-sm text-muted-foreground">{season.notes}</p>
          )}
        </CardContent>
      </Card>
    </li>
  );
}
