import { useState } from "react";
import { Flag, Shield, Skull, Trophy } from "lucide-react";
import { useSearchParams } from "react-router";

import { LoadingState } from "@/components/loading-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { HistoryTabs } from "@/history/components/HistoryTabs";
import { deriveSeason } from "@/history/season/derive";
import { EventCard } from "@/history/season/EventCard";
import { useSeasonArchive } from "@/history/season/useSeasonArchive";
import { cn } from "@/lib/utils";

export function SeasonHistoryPage() {
  const query = useSeasonArchive();
  const season = deriveSeason(query.data ?? { weeks: [], events: [] });
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState("all");
  const requestedWeek = Number(params.get("week"));
  const defaultWeek = season.weeks.filter((w) => w.record).at(-1)?.number ?? 1;
  const selected =
    Number.isInteger(requestedWeek) && requestedWeek >= 1 && requestedWeek <= 17
      ? requestedWeek
      : defaultWeek;
  const week = season.weeks[selected - 1];
  const events = week.events.filter(
    (e) =>
      filter === "all" ||
      (filter === "gulag"
        ? e.event_type.startsWith("gulag_")
        : e.event_type === "eliminated" || e.event_type === "champion"),
  );
  const hasConfirmed = season.confirmedWeeks > 0;
  const status = !week.record
    ? "Awaiting results"
    : week.record.status === "retracted"
      ? "Result withdrawn"
      : week.complete
        ? week.record.is_correction
          ? "Confirmed · Corrected"
          : "Confirmed"
        : week.record.status === "unresolved"
          ? "Needs a ruling"
          : week.record.status === "confirmed"
            ? "Incomplete archive"
            : "Provisional";
  function chooseWeek(value: number) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("week", String(value));
      return next;
    });
  }

  return (
    <section className="space-y-6">
      <HistoryTabs />
      <header className="space-y-2 pt-2">
        <p className="text-xs tracking-[0.2em] text-primary uppercase">
          2026 season history
        </p>
        <h2 className="text-4xl figures sm:text-5xl">
          The road to the last team.
        </h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Every gulag appearance. Every escape. Every official cut. Roster and
          money snapshots stay with the moment they happened.
        </p>
      </header>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Starting teams", value: "18", icon: Flag },
          {
            label: "Gulag qualifications",
            value: hasConfirmed ? String(season.qualifications) : "—",
            icon: Shield,
          },
          {
            label: "Official cuts",
            value: hasConfirmed ? String(season.cuts) : "—",
            icon: Skull,
          },
          {
            label: season.throughWeek
              ? `Alive after Week ${season.throughWeek}`
              : "Teams still alive",
            value: season.remaining === null ? "—" : String(season.remaining),
            icon: Trophy,
          },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-xl border bg-card p-4">
            <Icon
              className="mb-4 text-muted-foreground"
              size={17}
              aria-hidden="true"
            />
            <p className="text-3xl figures">{value}</p>
            <p className="mt-1 text-xs text-muted-foreground">{label}</p>
          </div>
        ))}
      </div>
      <div className="space-y-4 rounded-xl border bg-card p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg figures">18 teams. 17 weeks. One champion.</h3>
          <span className="text-xs text-muted-foreground">
            Select a week to see its story
          </span>
        </div>
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>
            <span
              aria-hidden="true"
              className="mr-2 inline-block size-2 rounded-sm bg-primary"
            />
            Confirmed
          </span>
          <span>
            <span
              aria-hidden="true"
              className="mr-2 inline-block size-2 rounded-sm border border-muted-foreground"
            />
            Scheduled path
          </span>
        </div>
        <div className="overflow-x-auto pb-2">
          <div
            className="flex min-w-[680px] items-end gap-1 sm:gap-2"
            aria-label="Weekly survival timeline"
          >
            {season.weeks.map((w) => (
              <button
                type="button"
                key={w.number}
                aria-pressed={selected === w.number}
                aria-label={`Week ${w.number}: ${w.rule.phase}, ${w.rule.remaining} teams ${w.complete ? "remaining, confirmed" : "scheduled to remain"}`}
                onClick={() => chooseWeek(w.number)}
                className={cn(
                  "group flex min-w-0 flex-1 flex-col items-center rounded-md px-1 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selected === w.number ? "bg-primary/10" : "hover:bg-muted",
                )}
              >
                <span className="mb-2 text-xs text-muted-foreground tabular-nums">
                  {w.rule.remaining}
                </span>
                <span
                  aria-hidden="true"
                  className={cn(
                    "block w-full rounded-t border",
                    w.complete
                      ? "border-primary bg-primary/70"
                      : "border-muted-foreground/30 bg-muted",
                    selected === w.number && "border-primary",
                  )}
                  style={{ height: `${w.rule.remaining * 6 + 12}px` }}
                />
                <span
                  className={cn(
                    "mt-2 text-xs tabular-nums",
                    selected === w.number
                      ? "text-primary"
                      : "text-muted-foreground",
                  )}
                >
                  {w.number}
                </span>
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Week 1: two qualify for gulag, nobody is cut. Week 12: two cuts.
          Outlined bars show the league schedule, not recorded results.
        </p>
      </div>
      {query.isPending && <LoadingState label="Loading 2026 history" />}
      {query.isError && (
        <Alert variant="destructive">
          <AlertTitle>Could not load 2026 history</AlertTitle>
          <AlertDescription>
            Recorded results are unavailable right now. The season schedule is
            shown above.{" "}
            <button onClick={() => void query.refetch()} className="underline">
              Try again
            </button>
          </AlertDescription>
        </Alert>
      )}
      {!query.isPending && !query.isError && (
        <section aria-label={`Week ${selected} history`} className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs text-primary">{week.rule.phase}</p>
              <h3 className="mt-1 text-2xl figures">Week {selected}</h3>
            </div>
            <span
              className={cn(
                "rounded-full border px-3 py-1 text-xs",
                week.complete
                  ? "border-emerald-300/30 text-emerald-300"
                  : "text-muted-foreground",
              )}
            >
              {status}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            {week.rule.description}
          </p>
          <div className="flex flex-wrap gap-2" aria-label="Event filters">
            {[
              ["all", "All events"],
              ["gulag", "Gulag"],
              ["cuts", "Cuts & champion"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
                className={cn(
                  "rounded-md border px-3 py-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  filter === value
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          {!week.record && (
            <div className="rounded-xl border border-dashed p-8 text-center">
              <Shield size={28} className="mx-auto mb-3 text-primary" />
              <p className="text-lg figures">The story starts here.</p>
              <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                No results recorded for Week {selected} yet. Gulag qualifiers
                and official cuts will appear separately when the week is
                recorded.
              </p>
            </div>
          )}
          {week.record && week.events.length === 0 && (
            <p className="rounded-xl border bg-card p-5 text-sm text-muted-foreground">
              {week.record.status === "retracted"
                ? "This result was withdrawn. A replacement has not been recorded."
                : "No event details recorded for this week yet."}
            </p>
          )}
          {!!week.events.length && events.length === 0 && (
            <p className="rounded-xl border bg-card p-5 text-sm text-muted-foreground">
              {week.complete && selected === 1 && filter === "cuts"
                ? "Nobody was cut in Week 1. All 18 teams remain alive."
                : "No matching events for this week."}
            </p>
          )}
          <div className="grid items-start gap-3 md:grid-cols-2">
            {events.map((event) => (
              <EventCard
                key={event.id}
                event={event}
                confirmed={week.complete}
              />
            ))}
          </div>
          {week.record && (
            <p className="text-xs text-muted-foreground">
              Revision {week.record.revision} · Rules{" "}
              {week.record.rules_version}.{" "}
              {week.complete
                ? "Finalized weekly record."
                : "This week does not contribute to confirmed totals."}
            </p>
          )}
        </section>
      )}
      <p className="border-t pt-4 text-xs text-muted-foreground">
        Detailed history begins in 2026. Totals cover {season.confirmedWeeks}{" "}
        confirmed {season.confirmedWeeks === 1 ? "week" : "weeks"}. A gulag
        qualification is not an elimination.
      </p>
    </section>
  );
}
