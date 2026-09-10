import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import type { SeasonElimination, SeasonResult } from "../types";

/**
 * What a season shows where an owner should be. Ben's ruling: a champion the loader could not
 * tie back to a member is "Unlisted" — the same word `/trades` uses for a player the directory
 * cannot name — never a blank, and never a real name pulled from `members.display_name`.
 */
export const UNLISTED_OWNER = "Unlisted";

/**
 * The focus ring every other bare `<button>` on the site carries (see `TradeCard`). This one is
 * not a `Button`, so it has to name the ring itself or it is a keyboard stop with no visible
 * focus at all.
 */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/**
 * One elimination line.
 *
 * A week the sheet recorded by name reads as the name. Otherwise it reads as the three counts,
 * and a count the sheet never carried says "not recorded" in words: a `0` there would claim
 * nobody went out that week, which is a different — and often wrong — fact.
 */
function eliminationText(
  entry: SeasonElimination,
  labelForMember: (memberId: number | null) => string | null,
): string {
  // Guarded on the id rather than trusting the resolver with a `null`: a week the sheet
  // recorded as counts has no member id at all, and asking for the name of nobody is how it
  // would end up captioned with somebody else's.
  const named = entry.memberId === null ? null : labelForMember(entry.memberId);
  if (named !== null) return `Week ${entry.week} · ${named} eliminated`;
  const parts = [
    entry.gulagOut === null
      ? "gulag not recorded"
      : `${entry.gulagOut} out of the gulag`,
    entry.poolOut === null
      ? "pool not recorded"
      : `${entry.poolOut} from the pool`,
    entry.remaining === null
      ? "remaining not recorded"
      : `${entry.remaining} remaining`,
  ];
  // The site's own separator, and deliberately not a dash: a dash between a label and a
  // missing number reads as the number itself, which is the misreading "not recorded" avoids.
  return `Week ${entry.week} · ${parts.join(", ")}`;
}

interface Props {
  season: SeasonResult;
  labelForMember: (memberId: number | null) => string | null;
}

export function SeasonCard({ season, labelForMember }: Props) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const runnerUps = [
    season.coChampionLabel && `Co-champion ${season.coChampionLabel}`,
    season.runnerUpLabel && `Runner-up ${season.runnerUpLabel}`,
    season.thirdLabel && `Third ${season.thirdLabel}`,
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
            {season.championLabel ?? UNLISTED_OWNER}
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
