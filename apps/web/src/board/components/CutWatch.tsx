import { useId, useState } from "react";
import { ChevronDown, Scissors } from "lucide-react";

import { cn } from "@/lib/utils";

import { cutWatch } from "../derive/cutWatch";
import { compareRosterPlayers } from "../derive/roster";
import { formatScore } from "../derive/score";
import type { BoardTeam } from "../types";

const projection = (points: number | null) => points?.toFixed(1) ?? "—";

function MatchupSide({ team }: { team: BoardTeam }) {
  return (
    <span className="min-w-0 text-center">
      <span className="block text-lg font-semibold break-words sm:text-2xl">
        {team.ownerName}
      </span>
      <span className="mt-1 block truncate text-xs text-muted-foreground sm:text-sm">
        {team.teamName}
      </span>
      <span className="mt-4 flex flex-wrap justify-center gap-x-4 gap-y-2 sm:gap-x-8">
        <span>
          <span className="block text-3xl figures text-destructive sm:text-4xl">
            {formatScore(team.score)}
          </span>
          <span className="mt-1 block text-xs text-muted-foreground">
            Actual
          </span>
        </span>
        <span>
          <span className="block text-3xl figures sm:text-4xl">
            {projection(team.projectedPoints)}
          </span>
          <span className="mt-1 block text-xs text-muted-foreground">
            Projected
          </span>
        </span>
      </span>
    </span>
  );
}

function Lineup({ team }: { team: BoardTeam }) {
  const starters = team.roster
    .filter((player) => player.slot === "starter")
    .sort(compareRosterPlayers);
  return (
    <div className="min-w-0">
      <h3 className="mb-3 font-semibold">{team.ownerName} · Starters</h3>
      {starters.length === 0 ? (
        <p className="text-sm text-muted-foreground">Lineup unavailable.</p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">
            {team.ownerName} starting lineup
          </caption>
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="pb-2 text-left font-normal">
                Player
              </th>
              <th scope="col" className="pb-2 pl-2 text-right font-normal">
                Actual
              </th>
              <th scope="col" className="pb-2 pl-2 text-right font-normal">
                Projected
              </th>
            </tr>
          </thead>
          <tbody>
            {starters.map((player) => (
              <tr
                key={player.sleeperPlayerId}
                className="border-t border-border/60"
              >
                <th scope="row" className="py-2 text-left font-normal">
                  <span className="mr-2 text-xs text-muted-foreground">
                    {player.lineupPosition ?? player.position}
                  </span>
                  {player.fullName}
                </th>
                <td className="py-2 pl-2 text-right tabular-nums">
                  {projection(player.livePoints)}
                </td>
                <td className="py-2 pl-2 text-right tabular-nums">
                  {projection(player.projectedPoints)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {team.emptySlots ? (
        <p className="mt-2 text-xs text-destructive">
          {team.emptySlots} empty lineup{" "}
          {team.emptySlots === 1 ? "slot" : "slots"}
        </p>
      ) : null}
      {team.isProvisional ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Projection is incomplete.
        </p>
      ) : null}
    </div>
  );
}

export function CutWatch({
  teams,
  week,
}: {
  teams: readonly BoardTeam[];
  week: number;
}) {
  const watch = cutWatch(teams, week);
  const [expanded, setExpanded] = useState(false);
  const titleId = useId();
  const detailsId = useId();
  const pairing = watch.kind === "ranked" ? watch.teams.slice(0, 2) : [];

  return (
    <section
      aria-labelledby={titleId}
      className="overflow-hidden rounded-xl border border-destructive/30 bg-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-destructive/15 bg-destructive/5 px-4 py-3">
        <h2
          id={titleId}
          className="flex items-center gap-2 text-lg font-semibold"
        >
          <Scissors className="size-4 text-destructive" aria-hidden="true" />
          Cut watch
        </h2>
        <span className="text-xs font-medium text-destructive">
          Week {week} ·{" "}
          {watch.kind === "ranked"
            ? watch.tied
              ? "Cutoff tied"
              : "Projected bottom two"
            : "Gulag watch"}
        </span>
      </div>
      {watch.kind === "waiting" ? (
        <p className="p-4 text-sm text-muted-foreground">{watch.message}</p>
      ) : (
        <>
          <button
            type="button"
            aria-label={
              expanded ? "Hide matchup details" : "Show matchup details"
            }
            aria-expanded={expanded}
            aria-controls={detailsId}
            onClick={() => setExpanded((value) => !value)}
            className="block w-full px-3 py-5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset sm:px-6"
          >
            <span className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 sm:gap-6">
              <MatchupSide team={pairing[0].team} />
              <span className="rounded-full border border-destructive/20 bg-destructive/5 px-2 py-2 text-xs font-semibold text-destructive sm:px-3">
                VS
              </span>
              <MatchupSide team={pairing[1].team} />
            </span>
            <span className="mt-5 flex items-center justify-center gap-2 text-xs text-muted-foreground">
              {expanded ? "Hide details" : "Matchup details"}
              <ChevronDown
                aria-hidden="true"
                className={cn("size-4", expanded && "rotate-180")}
              />
            </span>
          </button>
          <p className="px-4 pb-4 text-center text-xs text-muted-foreground">
            {watch.tied
              ? "Projections tied at the cutoff. Pairing is provisional."
              : `On course for the Week ${week + 1} gulag.`}
          </p>
          <div
            id={detailsId}
            hidden={!expanded}
            className="space-y-5 border-t border-destructive/15 p-4 sm:p-6"
          >
            {expanded ? (
              <>
                <div className="space-y-2 text-sm text-muted-foreground">
                  <p>
                    Bottom two enter the Week {week + 1} gulag.{" "}
                    {week === 1
                      ? "Nobody is cut this week."
                      : "Current gulag teams are excluded."}
                  </p>
                  {watch.tied ? (
                    <p>
                      Teams at or below the cutoff:{" "}
                      {watch.teams.map(({ team }) => team.ownerName).join(", ")}
                      . The tie is unresolved.
                    </p>
                  ) : (
                    <div className="grid gap-2 sm:grid-cols-2">
                      {pairing.map(({ team, gap }) => (
                        <p key={team.teamId}>
                          <span className="font-medium text-foreground">
                            {team.ownerName}:{" "}
                          </span>
                          {gap?.toFixed(2)} pts to the safety line
                        </p>
                      ))}
                    </div>
                  )}
                  <p className="text-xs">
                    Ranked by weekly projections. The safety line is the
                    third-lowest eligible projection. Results are not official.
                  </p>
                </div>
                <div className="grid gap-6 md:grid-cols-2">
                  {pairing.map(({ team }) => (
                    <Lineup key={team.teamId} team={team} />
                  ))}
                </div>
              </>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}
