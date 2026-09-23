import { useId, useState } from "react";
import { ArrowDownRight, ArrowUpRight, ChevronDown } from "lucide-react";

import {
  useWeeklyScoreRecords,
  type WeeklyScoreRecord,
} from "../useWeeklyScoreRecords";
import { ScoreRecordEntry } from "./ScoreRecordEntry";

function RecordList({
  title,
  rows,
  high,
  fullLineupRows,
}: {
  title: string;
  rows: WeeklyScoreRecord[];
  high: boolean;
  fullLineupRows?: WeeklyScoreRecord[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [fullLineupsOnly, setFullLineupsOnly] = useState(false);
  const listId = useId();
  const selectedRows = fullLineupsOnly ? (fullLineupRows ?? []) : rows;
  const visibleRows = selectedRows.filter(
    (row) => row.rank <= (expanded ? 10 : 5),
  );
  const hasMore = selectedRows.some((row) => row.rank > 5);
  const Icon = high ? ArrowUpRight : ArrowDownRight;
  return (
    <article className="overflow-hidden rounded-xl border bg-card">
      <h3 className="flex items-center gap-2 border-b px-4 py-3 text-sm font-medium">
        <Icon
          size={17}
          className={high ? "text-primary" : "text-muted-foreground"}
          aria-hidden="true"
        />
        {title}
      </h3>
      {fullLineupRows !== undefined && (
        <div className="space-y-2 border-b px-4 py-3">
          <label className="flex cursor-pointer items-center justify-between gap-3 text-sm">
            Full lineups only
            <span className="relative inline-flex shrink-0">
              <input
                type="checkbox"
                role="switch"
                checked={fullLineupsOnly}
                onChange={(event) => setFullLineupsOnly(event.target.checked)}
                aria-controls={listId}
                className="peer sr-only"
              />
              <span
                aria-hidden="true"
                className="h-5 w-9 rounded-full border bg-muted transition-colors peer-checked:bg-primary peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-card after:absolute after:top-0.5 after:left-0.5 after:size-4 after:rounded-full after:bg-foreground after:transition-transform peer-checked:after:translate-x-4 peer-checked:after:bg-primary-foreground"
              />
            </span>
          </label>
          {fullLineupsOnly && (
            <p className="text-xs text-muted-foreground">
              Every starting slot filled. Players on bye or out injured still
              count.
            </p>
          )}
        </div>
      )}
      {selectedRows.length === 0 && (
        <p className="p-4 text-sm text-muted-foreground">
          No qualifying scores recorded yet.
        </p>
      )}
      <ol id={listId} aria-label={title} className="divide-y">
        {visibleRows.map((row, index) => (
          <ScoreRecordEntry key={row.key} record={row} leading={index === 0} />
        ))}
      </ol>
      {hasMore && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-label={`${expanded ? "Show less" : "Show top 10"}: ${title}`}
          onClick={() => setExpanded((value) => !value)}
          className="flex w-full items-center justify-center gap-2 border-t px-4 py-3 text-sm text-primary outline-none hover:bg-primary/5 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        >
          {expanded ? "Show less" : "Show top 10"}
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={expanded ? "rotate-180" : ""}
          />
        </button>
      )}
    </article>
  );
}

export function WeeklyScoreRecords() {
  const query = useWeeklyScoreRecords();
  return (
    <section
      aria-labelledby="weekly-records-heading"
      className="space-y-3 pb-4"
    >
      <div>
        <h2 id="weekly-records-heading" className="text-2xl figures">
          All-time weekly scores
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          The highest and lowest weekly scores in the available league records.
          Select a score to see its roster. Expand each card for the top 10.
          Ties share a rank.
        </p>
      </div>
      {query.isPending ? (
        <p
          role="status"
          className="rounded-xl border bg-card p-5 text-sm text-muted-foreground"
        >
          Loading score records…
        </p>
      ) : query.isError ? (
        <div role="alert" className="rounded-xl border bg-card p-5 text-sm">
          Could not load score records.{" "}
          <button className="underline" onClick={() => void query.refetch()}>
            Try again
          </button>
        </div>
      ) : !query.data?.coverage.length ? (
        <p className="rounded-xl border bg-card p-5 text-sm text-muted-foreground">
          No confirmed weekly scores are available yet.
        </p>
      ) : (
        <>
          <div className="grid items-start gap-3 md:grid-cols-2">
            <RecordList
              title="Highest weekly scores"
              rows={query.data.highs}
              high
            />
            <RecordList
              title="Lowest weekly scores"
              rows={query.data.lows}
              fullLineupRows={query.data.full_lineup_lows ?? []}
              high={false}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Recorded seasons:{" "}
            {query.data.coverage.map((c) => c.season).join(", ")}.{" "}
            {Math.min(...query.data.coverage.map((c) => c.season)) > 2019 &&
              "Earlier seasons aren't available yet. "}
            Current-season scores enter after confirmation. Post-elimination
            lineups are excluded.
          </p>
        </>
      )}
    </section>
  );
}
