import { ChevronRight } from "lucide-react";
import { Link } from "react-router";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import {
  useScoreRecordRoster,
  type ScoringPlayer,
} from "../useScoreRecordRoster";
import type { WeeklyScoreRecord } from "../useWeeklyScoreRecords";

function PlayerTable({
  players,
  title,
}: {
  players: ScoringPlayer[];
  title: string;
}) {
  return (
    <table className="w-full text-left text-sm">
      <caption className="pb-2 text-left text-base font-medium">
        {title}
      </caption>
      <thead className="text-xs text-muted-foreground">
        <tr>
          <th className="pr-3 pb-2 font-normal">Slot</th>
          <th className="pb-2 font-normal">Player</th>
          <th className="pb-2 text-right font-normal">Points</th>
        </tr>
      </thead>
      <tbody>
        {players.map((player, index) => (
          <tr key={`${index}-${player.player_id}`} className="border-t">
            <td className="py-3 pr-3 text-xs text-muted-foreground">
              {player.slot}
            </td>
            <td className="py-3">
              <span
                className={
                  player.player_id
                    ? "font-medium"
                    : "text-muted-foreground italic"
                }
              >
                {player.player_label}
              </span>
              {player.position && (
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {player.position}
                </span>
              )}
            </td>
            <td className="py-3 text-right tabular-nums">
              {player.player_id === null ? (
                "—"
              ) : player.points === null ? (
                <span aria-label="Points not recorded">—</span>
              ) : (
                player.points.toFixed(2)
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RosterContents({ record }: { record: WeeklyScoreRecord }) {
  // Dialog content mounts only when opened, so leaderboard reads stay small.
  const query = useScoreRecordRoster(record.key);
  const detail = query.data;
  const roster = detail?.roster;
  const header = detail ?? record;
  return (
    <>
      <DialogHeader>
        <DialogTitle className="text-xl">
          {header.manager_label || header.team_label}
        </DialogTitle>
        <DialogDescription className="text-sm">
          {header.team_label} · {header.season} · Week {header.week}
        </DialogDescription>
      </DialogHeader>
      <div className="min-h-0 space-y-5 overflow-y-auto pr-1">
        <div className="flex items-end justify-between gap-3 rounded-lg bg-primary/5 p-4">
          <div>
            <p className="text-xs text-muted-foreground">Weekly score</p>
            <p className="mt-1 text-4xl figures text-primary">
              {header.points.toFixed(2)}
            </p>
          </div>
          {roster && (
            <p className="text-sm text-muted-foreground">
              {roster.starters.filter((p) => p.player_id !== null).length} of{" "}
              {roster.starters.length} starting slots filled
            </p>
          )}
        </div>
        {query.isPending ? (
          <p role="status" className="text-sm">
            Loading saved roster…
          </p>
        ) : query.isError ? (
          <p role="alert" className="text-sm">
            Could not load this week's roster.{" "}
            <button className="underline" onClick={() => void query.refetch()}>
              Try again
            </button>
          </p>
        ) : !roster ? (
          <p className="text-sm text-muted-foreground">
            The saved roster is unavailable for this record. The result may have
            changed.
          </p>
        ) : (
          <>
            <PlayerTable title="Starting lineup" players={roster.starters} />
            {roster.bench.length > 0 && (
              <div className="border-t pt-4">
                <PlayerTable
                  title="Bench · not included in team score"
                  players={roster.bench}
                />
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              This is the saved roster for this scoring week. Team totals
              include any scoring adjustments. A dash means an empty slot or
              player points were not recorded.
            </p>
          </>
        )}
        {record.season === 2026 && (
          <Link
            className="inline-block text-sm text-primary underline underline-offset-4"
            to={`/current-season?week=${record.week}`}
          >
            View all teams in {record.season} · Week {record.week}
          </Link>
        )}
      </div>
    </>
  );
}

export function ScoreRecordEntry({
  record,
  leading,
}: {
  record: WeeklyScoreRecord;
  leading: boolean;
}) {
  return (
    <li>
      <Dialog>
        <DialogTrigger asChild>
          <button
            type="button"
            aria-label={`View roster: ${record.manager_label || record.team_label}, ${record.season} Week ${record.week}, ${record.points.toFixed(2)} points`}
            className={`flex w-full items-center gap-3 px-4 text-left outline-none hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset ${leading ? "bg-primary/5 py-5" : "py-3"}`}
          >
            <span
              className="w-4 shrink-0 text-xs text-muted-foreground tabular-nums"
              aria-label={`Rank ${record.rank}`}
            >
              {record.rank}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-base font-medium break-words">
                {record.manager_label || record.team_label}
              </span>
              {record.manager_label &&
                record.manager_label !== record.team_label && (
                  <span className="mt-0.5 block text-xs break-words text-muted-foreground">
                    {record.team_label}
                  </span>
                )}
              <span className="mt-1 block text-sm text-muted-foreground">
                {record.season} · Week {record.week}
              </span>
            </span>
            <span className="shrink-0 text-right">
              <span
                className={`${leading ? "text-3xl text-primary" : "text-xl"} block figures tabular-nums`}
              >
                {record.points.toFixed(2)}
              </span>
              <span className="block text-xs text-muted-foreground">
                points
              </span>
            </span>
            <ChevronRight
              size={16}
              className="shrink-0 text-muted-foreground"
              aria-hidden="true"
            />
          </button>
        </DialogTrigger>
        <DialogContent className="max-w-xl">
          <RosterContents record={record} />
        </DialogContent>
      </Dialog>
    </li>
  );
}
