import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { HistoryListSkeleton } from "@/history/components/HistorySkeleton";
import { SeasonCard } from "@/history/components/SeasonCard";
import { CARD_GRID } from "@/history/layout";
import { useSeasonResults } from "@/history/useSeasonResults";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

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

      {/* The same skeleton the shell shows while this page's chunk is on its way, so the
          handoff from one to the other moves nothing. */}
      {isPending && <HistoryListSkeleton />}

      {!isPending && seasons.length === 0 && (
        <p
          className={`rounded-xl border bg-card p-4 text-sm ${REVEAL_CLASS}`}
          style={revealStyle(0)}
        >
          No seasons loaded yet.
        </p>
      )}

      {/* The champion cards are the whole page (Ben, 2026-09-10: the winners table said
          the same thing twice). Each card's place in the cascade is its place in the list. */}
      {seasons.length > 0 && (
        <ul aria-label="Seasons" className={CARD_GRID}>
          {seasons.map((season, index) => (
            <SeasonCard
              key={season.season}
              season={season}
              revealIndex={index}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
