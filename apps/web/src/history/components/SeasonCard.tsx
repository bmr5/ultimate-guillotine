import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import { FORMER_MANAGER, seasonPlacingLabel } from "../derive/ownerLabel";
import type { SeasonElimination, SeasonResult } from "../types";

/**
 * The focus ring every other bare `<button>` on the site carries (see `TradeCard`). This one is
 * not a `Button`, so it has to name the ring itself or it is a keyboard stop with no visible
 * focus at all.
 */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/**
 * One elimination line.
 *
 * A week the sheet recorded by member id reads as a person — the name when the directory has
 * one, otherwise "Former manager". A week the sheet recorded as counts reads as the figures it
 * actually wrote down, and only those: a `null` count contributes no clause at all.
 *
 * That is not the same as saying so per figure. Most weeks are missing one of the two for a
 * structural reason rather than a gap in the file — 2023 ran without a general pool, so its
 * grid has no pool column and every one of its rows would otherwise end "pool not recorded" —
 * and a caveat that fires on every line stops being read as one. What a line never does is
 * print a `0` for a missing figure (that would claim nobody went out, a different and usually
 * wrong fact) or a dash in its place (which reads as the number itself).
 *
 * A week that recorded neither figure has nothing to report, and says exactly that.
 */
function eliminationText(
  entry: SeasonElimination,
  labelForMember: (memberId: number | null) => string | null,
): string {
  // Guarded on the id rather than trusting the resolver with a `null`: a week the sheet
  // recorded as counts has no member id at all, and asking for the name of nobody is how it
  // would end up captioned with somebody else's.
  if (entry.memberId !== null) {
    // The sheet named somebody this week, so the line is about a person either way. When the
    // directory cannot say who, that is a manager who has left, not a reason to fall back to
    // the counts — the counts describe a different kind of week, and a week that named one
    // person usually has no counts to fall back to at all.
    const named = labelForMember(entry.memberId);
    return `Week ${entry.week} · ${named ?? FORMER_MANAGER} eliminated`;
  }
  const parts = [
    entry.gulagOut === null ? null : `${entry.gulagOut} out of the gulag`,
    entry.poolOut === null ? null : `${entry.poolOut} from the pool`,
  ].filter((part): part is string => part !== null);
  // `·` is the site's own separator, and deliberately not a dash: a dash before a missing
  // figure reads as the figure itself, which is the misreading this whole function avoids.
  return `Week ${entry.week} · ${
    parts.length === 0 ? "not recorded" : parts.join(", ")
  }`;
}

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
  labelForMember: (memberId: number | null) => string | null;
}

export function SeasonCard({ season, labelForMember }: Props) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
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
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Champion {season.season}
          </p>
          <p className="text-2xl font-semibold">
            {seasonPlacingLabel(season.championLabel, season.championMemberId)}
          </p>
          {runnerUps.length > 0 && (
            <p className="text-sm text-muted-foreground">
              {runnerUps.join(" · ")}
            </p>
          )}

          {season.eliminations.length > 0 && (
            <Collapsible open={open} onOpenChange={setOpen}>
              {/* A real <button>, not a Radix trigger, so the card owns its `aria-controls`. */}
              <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                aria-expanded={open}
                aria-controls={panelId}
                className={cn(
                  "flex items-center gap-1 text-sm font-medium",
                  FOCUS_RING_CLASS,
                )}
              >
                Eliminations
                <ChevronDown
                  aria-hidden
                  className={cn(
                    "h-4 w-4 transition-transform",
                    open && "rotate-180",
                  )}
                />
              </button>
              {/*
                Force-mounted and hidden with the `hidden` attribute rather than unmounted, so
                the `aria-controls` above always resolves to a real element — the arrangement
                `TradeCard` and the board's `TeamCard` both use. The rows themselves still mount
                lazily, so a page of collapsed cards carries no hidden elimination lists.
              */}
              <CollapsibleContent id={panelId} forceMount hidden={!open}>
                {open ? (
                  <ul className="mt-2 space-y-1 border-t pt-2 text-sm">
                    {season.eliminations.map((entry) => (
                      <li key={entry.order}>
                        {eliminationText(entry, labelForMember)}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </CollapsibleContent>
            </Collapsible>
          )}

          {season.notes !== null && (
            <p className="text-sm text-muted-foreground">{season.notes}</p>
          )}
        </CardContent>
      </Card>
    </li>
  );
}
