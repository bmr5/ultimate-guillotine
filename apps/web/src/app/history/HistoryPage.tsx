import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { SeasonCard } from "@/history/components/SeasonCard";
import { WinnersStrip } from "@/history/components/WinnersStrip";
import { useSeasonResults } from "@/history/useSeasonResults";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

/**
 * Where the season cards start in the page's cascade: the winners strip is place 0, and the
 * cards follow it. The alerts, the placeholder and the empty state stand where the strip would.
 */
const AFTER_WINNERS = 1;

export function HistoryPage() {
  const { seasons, isPending, errors } = useSeasonResults();

  return (
    <section className="space-y-3">
      {/* Keyed by source, not by message: one outage fails both queries with the same text, and
          two alerts sharing a key would leave React rendering only one of them. */}
      {errors.map(({ source, error }) => (
        <Alert
          key={source}
          variant="destructive"
          className={REVEAL_CLASS}
          style={revealStyle(0)}
        >
          <AlertTitle>Could not load {source.toLowerCase()}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ))}

      {/* Wrapped rather than given the cascade class: `Skeleton` already animates its pulse,
          and one element cannot run both. */}
      {isPending && (
        <div className={REVEAL_CLASS} style={revealStyle(0)}>
          <Skeleton className="h-40 w-full" />
        </div>
      )}

      {!isPending && seasons.length === 0 && (
        <p
          className={`rounded-xl border bg-card p-4 text-sm ${REVEAL_CLASS}`}
          style={revealStyle(0)}
        >
          No seasons loaded yet.
        </p>
      )}

      {seasons.length > 0 && (
        <>
          <WinnersStrip seasons={seasons} />
          <ul
            aria-label="Seasons"
            className="grid grid-cols-1 gap-2 sm:grid-cols-2"
          >
            {seasons.map((season, index) => (
              <SeasonCard
                key={season.season}
                season={season}
                revealIndex={AFTER_WINNERS + index}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
