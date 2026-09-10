import { Anchor } from "lucide-react";

import { ExplainedBadge } from "@/components/explained-badge";

import { DRAFTED_HERE_LABEL, draftedHereDescription } from "../derive/draft";

/**
 * The anchor beside a player still on the team that drafted him. Ben (2026-09-10) chose a small
 * glyph with a tooltip over the price itself on the row. An `ExplainedBadge`, so a tap opens the
 * sentence on a phone and a screen reader gets it either way; the icon is a one-line swap.
 */
export function DraftedMark({
  ownerName,
  amount,
}: {
  ownerName: string;
  amount: number;
}) {
  return (
    <ExplainedBadge
      data-drafted-here
      aria-label={DRAFTED_HERE_LABEL}
      description={draftedHereDescription(ownerName, amount)}
      className="-my-2 ml-1 inline-flex min-h-[44px] shrink-0 items-center rounded-md px-0.5 text-muted-foreground"
    >
      <Anchor aria-hidden="true" className="h-3 w-3" />
    </ExplainedBadge>
  );
}
