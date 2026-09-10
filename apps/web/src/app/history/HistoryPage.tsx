import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { SeasonCard } from "@/history/components/SeasonCard";
import { useSeasonResults } from "@/history/useSeasonResults";

export function HistoryPage() {
  const { seasons, isPending, errors } = useSeasonResults();

  return (
    <section className="space-y-3">
      {/* Keyed by source, not by message: one outage fails both queries with the same text, and
          two alerts sharing a key would leave React rendering only one of them. */}
      {errors.map(({ source, error }) => (
        <Alert key={source} variant="destructive">
          <AlertTitle>Could not load {source.toLowerCase()}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ))}

      {isPending && <Skeleton className="h-40 w-full" />}

      {!isPending && seasons.length === 0 && (
        <p className="rounded-xl border bg-card p-4 text-sm">
          No seasons loaded yet.
        </p>
      )}

      {/* The champion cards are the whole page (Ben, 2026-09-10: the winners table said
          the same thing twice). */}
      {seasons.length > 0 && (
        <ul
          aria-label="Seasons"
          className="grid grid-cols-1 gap-2 sm:grid-cols-2"
        >
          {seasons.map((season) => (
            <SeasonCard key={season.season} season={season} />
          ))}
        </ul>
      )}
    </section>
  );
}
