import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

import { eventLabel } from "./derive";
import type { ArchiveEvent } from "./types";
import { useEventPlayers } from "./useSeasonArchive";

function stamp(value: string | null) {
  if (!value) return "Time not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Time not recorded"
    : date.toLocaleString("en-US", {
        timeZone: "America/Chicago",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      });
}

export function EventCard({
  event,
  confirmed,
}: {
  event: ArchiveEvent;
  confirmed: boolean;
}) {
  const [open, setOpen] = useState(false);
  const players = useEventPlayers(event.id, open);
  const cut = event.event_type === "eliminated";
  const survived =
    event.event_type === "gulag_survived" || event.event_type === "champion";
  const tone = cut
    ? "text-destructive border-destructive/30"
    : survived
      ? "text-emerald-300 border-emerald-300/30"
      : "text-primary border-primary/30";
  const money =
    event.faab_remaining === null
      ? "Not recorded"
      : `$${event.faab_remaining.toLocaleString("en-US")}`;
  return (
    <article className={cn("overflow-hidden rounded-xl border bg-card", tone)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${eventLabel(event)}: ${event.team_label}${confirmed ? "" : " (not final)"}`}
        aria-controls={`event-${event.id}`}
        className="flex w-full items-center justify-between gap-4 p-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        <span className="min-w-0 space-y-2">
          <span className="block text-xs font-medium">
            {eventLabel(event)}
            {!confirmed && " · Not final"}
          </span>
          <span className="block text-xl figures text-foreground">
            {event.team_label}
          </span>
          <span className="block text-xs text-muted-foreground">
            {event.manager_label && `${event.manager_label} · `}
            {event.contest_week !== null
              ? `Gulag contest: Week ${event.contest_week}`
              : "Season result"}
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-4 text-foreground">
          <span className="text-right">
            <span className="block text-2xl figures">
              {event.score === null ? "—" : event.score.toFixed(2)}
            </span>
            <span className="block text-xs text-muted-foreground">points</span>
          </span>
          {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </span>
      </button>
      {open && (
        <div
          id={`event-${event.id}`}
          className="space-y-4 border-t p-4 text-sm text-foreground"
        >
          {event.qualification_week !== null && (
            <p className="text-muted-foreground">
              Qualified in Week {event.qualification_week}
              {event.contest_week !== null &&
                ` for the Week ${event.contest_week} contest`}
              .
            </p>
          )}
          {event.qualifier_label &&
            event.qualifier_label !== event.team_label && (
              <p>
                Original qualifier: {event.qualifier_label}. Actual participant:{" "}
                {event.team_label}.
              </p>
            )}
          {event.beneficiary_label && (
            <p>Taking the gulag place of {event.beneficiary_label}.</p>
          )}
          {event.opponent_label && (
            <p>
              Opponent: {event.opponent_label} ·{" "}
              {event.opponent_score === null
                ? "Score not recorded"
                : `${event.opponent_score.toFixed(2)} points`}
            </p>
          )}
          <dl className="grid grid-cols-2 gap-4 rounded-lg bg-muted p-3">
            <div>
              <dt className="text-xs text-muted-foreground">
                Money at this event
              </dt>
              <dd className="mt-1 text-xl figures text-primary">{money}</dd>
              <dd className="mt-1 text-xs text-muted-foreground">
                {event.money_coverage === "partial"
                  ? "Partial money record · "
                  : ""}
                {stamp(event.money_as_of)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Roster cutoff</dt>
              <dd className="mt-1">{stamp(event.effective_at)}</dd>
              <dd className="mt-1 text-xs text-muted-foreground">
                {event.roster_coverage === "complete"
                  ? "Complete saved roster"
                  : event.roster_coverage === "partial"
                    ? "Partial saved roster"
                    : "Roster not recorded"}
              </dd>
            </div>
          </dl>
          <p className="text-muted-foreground">
            {cut
              ? "This is the roster at the official cut."
              : "This snapshot is separate from the roster at any later cut."}{" "}
            Later trades and drops do not change it.
          </p>
          {players.isPending && <p role="status">Loading saved roster…</p>}
          {players.isError && (
            <div role="alert">
              Could not load the saved roster.{" "}
              <button
                className="underline"
                onClick={() => void players.refetch()}
              >
                Retry
              </button>
            </div>
          )}
          {!players.isPending &&
            !players.isError &&
            players.data?.length === 0 && (
              <p>
                {event.roster_coverage === "complete"
                  ? "The saved roster contains no players."
                  : "No player details recorded for this snapshot."}
              </p>
            )}
          {!!players.data?.length && (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs sm:text-sm">
                <caption className="sr-only">
                  Saved roster for {event.team_label}: {eventLabel(event)}
                </caption>
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="py-2 font-normal">Player</th>
                    <th className="px-2 font-normal">Role</th>
                    <th className="text-right font-normal">Points</th>
                  </tr>
                </thead>
                <tbody>
                  {players.data.map((player) => (
                    <tr key={player.player_id} className="border-t">
                      <td className="py-2">
                        {player.player_label}
                        <span className="ml-2 text-muted-foreground">
                          {player.position}
                        </span>
                        {player.keeper && (
                          <span className="ml-2 text-primary">Keeper</span>
                        )}
                      </td>
                      <td className="px-2 text-muted-foreground">
                        {player.started ? "Starter" : (player.slot ?? "Held")}
                        {!player.owned_at_cutoff && " · Left before cutoff"}
                      </td>
                      <td className="text-right tabular-nums">
                        {player.points === null
                          ? "—"
                          : player.points.toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
