import { ChevronDown } from "lucide-react";

import type { ArchiveEvent, ArchiveWeek, WeeklyTeam } from "./types";
import { useWeeklyRosters } from "./useWeeklyRosters";

function stamp(value: string) {
  return new Date(value).toLocaleString("en-US", {
    timeZone: "America/Chicago",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function SavedRoster({ team }: { team: WeeklyTeam }) {
  return (
    <div className="space-y-3 border-t bg-muted/20 px-4 py-4 sm:px-6">
      <p className="text-sm text-muted-foreground">
        {team.roster_at
          ? `Roster saved ${stamp(team.roster_at)}.`
          : "Roster time not recorded."}{" "}
        {team.roster_coverage === "partial" && "Partial roster record. "}
        Later trades and drops do not change this lineup.
      </p>
      {team.players.length ? (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">
            Saved roster for {team.team_label}
          </caption>
          <thead className="text-muted-foreground">
            <tr>
              <th className="pb-2 font-normal">Player</th>
              <th className="px-2 pb-2 font-normal">Role</th>
              <th className="pb-2 text-right font-normal">Points</th>
            </tr>
          </thead>
          <tbody>
            {team.players.map((player) => (
              <tr key={player.player_id} className="border-t">
                <td className="py-3">
                  <span className="block font-medium">
                    {player.player_label}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {player.position}
                  </span>
                </td>
                <td className="px-2 py-3 text-muted-foreground">
                  {player.started
                    ? "Starter"
                    : player.slot === "ir"
                      ? "IR"
                      : player.slot === "taxi"
                        ? "Taxi"
                        : "Bench"}
                  {!player.owned_at_cutoff && (
                    <span className="block text-xs">Left before cutoff</span>
                  )}
                </td>
                <td className="py-3 text-right tabular-nums">
                  {player.points === null ? (
                    <span aria-label="Points not recorded">—</span>
                  ) : (
                    player.points.toFixed(2)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-sm">
          No saved player details are available for this team.
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        Team totals include any commissioner scoring adjustments. A dash means
        player points were not recorded.
      </p>
    </div>
  );
}

export function WeeklyScores({
  record,
  events,
}: {
  record: ArchiveWeek | null;
  events: ArchiveEvent[];
}) {
  const confirmed = record?.status === "confirmed";
  const query = useWeeklyRosters(confirmed ? record.id : undefined);
  if (!confirmed)
    return (
      <div className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
        {record?.status === "retracted"
          ? "This week's result was withdrawn. Scores will return when a replacement is confirmed."
          : "Scores and saved rosters will appear here when this week is confirmed."}
      </div>
    );
  if (query.isPending)
    return <p role="status">Loading weekly scores and rosters…</p>;
  if (query.isError)
    return (
      <div role="alert" className="rounded-xl border p-5 text-sm">
        Could not load weekly scores and rosters.{" "}
        <button className="underline" onClick={() => void query.refetch()}>
          Try again
        </button>
      </div>
    );
  const teams = [...(query.data ?? [])].sort(
    (a, b) => b.points - a.points || a.team_label.localeCompare(b.team_label),
  );
  if (!teams.length)
    return (
      <p className="rounded-xl border p-5 text-sm text-muted-foreground">
        No team scores are available for this confirmed week yet.
      </p>
    );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-muted-foreground">
        <p>{teams.length} teams · Highest score first</p>
        <p>Select a team to see its saved roster</p>
      </div>
      <div className="overflow-hidden rounded-xl border bg-card">
        {teams.map((team, index) => {
          const rank =
            teams.findIndex((other) => other.points === team.points) + 1;
          const outcome = events.find(
            (event) =>
              event.team_id === team.team_id &&
              ["eliminated", "champion", "gulag_qualified"].includes(
                event.event_type,
              ),
          );
          return (
            <details
              key={`${record.id}-${team.team_id}`}
              className="group border-b last:border-b-0"
            >
              <summary className="flex cursor-pointer list-none items-center gap-3 p-4 outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset sm:gap-5 sm:px-6 [&::-webkit-details-marker]:hidden">
                <span
                  className={`w-6 shrink-0 text-center text-sm tabular-nums ${index === 0 ? "text-primary" : "text-muted-foreground"}`}
                  aria-label={`Rank ${rank}`}
                >
                  {rank}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-base font-medium break-words">
                    {team.team_label}
                  </span>
                  <span className="mt-1 block text-sm text-muted-foreground">
                    {team.manager_label}
                    {outcome && (
                      <span
                        className={
                          outcome.event_type === "eliminated"
                            ? "ml-2 text-destructive"
                            : "ml-2 text-primary"
                        }
                      >
                        {outcome.event_type === "gulag_qualified"
                          ? `Week ${outcome.contest_week} gulag`
                          : outcome.event_type === "champion"
                            ? "Champion"
                            : "Eliminated"}
                      </span>
                    )}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className="block text-2xl figures tabular-nums">
                    {team.points.toFixed(2)}
                  </span>
                  <span className="text-xs text-muted-foreground">points</span>
                </span>
                <ChevronDown
                  size={18}
                  className="shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                  aria-hidden="true"
                />
              </summary>
              <SavedRoster team={team} />
            </details>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        Confirmed {stamp(record.checked_at)}. Stat corrections update this
        week's scores.
      </p>
    </div>
  );
}
