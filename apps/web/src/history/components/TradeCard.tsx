import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import type { CatalogTrade } from "../types";

/**
 * The focus ring every other bare `<button>` on the site carries (see `TeamCard`). This one is
 * not a `Button`, so it has to name the ring itself or it is a keyboard stop with no visible
 * focus at all.
 */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/** Shown in the panel when a trade carries no itemised assets. */
const NO_ASSETS_TEXT = "No itemised assets recorded";

function whenLabel(trade: CatalogTrade): string {
  if (trade.week !== null) return `${trade.season} · Week ${trade.week}`;
  if (trade.occurredOn !== null) return `${trade.season} · ${trade.occurredOn}`;
  return `${trade.season}`;
}

function assetLabel(asset: CatalogTrade["assets"][number]): string {
  if (asset.kind === "player") {
    return asset.position ? `${asset.name} (${asset.position})` : asset.name;
  }
  if (asset.kind === "faab") return `${asset.amount} FAAB`;
  return asset.label.replace(/_/g, " ");
}

export function TradeCard({ trade }: { trade: CatalogTrade }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const missing = Math.max(trade.partyCount - trade.parties.length, 0);

  return (
    <li data-rescinded={trade.rescinded} className="list-none">
      <Card className={cn(trade.rescinded && "opacity-60")}>
        <CardContent className="p-3">
          <Collapsible open={open} onOpenChange={setOpen}>
            {/* A real <button>, not a Radix trigger, so the card owns its `aria-controls`. */}
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              aria-expanded={open}
              aria-controls={panelId}
              className={cn(
                "flex w-full items-start justify-between gap-2 text-left",
                FOCUS_RING_CLASS,
              )}
            >
              <span className="min-w-0">
                <span className="block text-xs text-muted-foreground">
                  {whenLabel(trade)}
                </span>
                <span
                  className={cn(
                    "block truncate text-sm font-medium",
                    trade.rescinded && "line-through",
                  )}
                >
                  {trade.tradeType} · {trade.structure}
                </span>
              </span>
              <ChevronDown
                aria-hidden
                className={cn(
                  "mt-1 h-4 w-4 shrink-0 transition-transform",
                  open && "rotate-180",
                )}
              />
            </button>

            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {trade.parties.map((party) => (
                <Badge key={party.memberId} variant="secondary">
                  {party.label}
                </Badge>
              ))}
              {missing > 0 && (
                <span className="text-xs text-muted-foreground">
                  and {missing} unidentified owner{missing === 1 ? "" : "s"}
                </span>
              )}
              {trade.faabTotal !== null && (
                <Badge variant="outline">{trade.faabTotal} FAAB</Badge>
              )}
              {trade.confidence !== "high" && !trade.registered && (
                <Badge variant="outline">low confidence</Badge>
              )}
              {trade.rescinded && (
                <Badge variant="destructive">rescinded</Badge>
              )}
              <Badge variant={trade.registered ? "default" : "outline"}>
                {trade.sourceLabel}
              </Badge>
            </div>

            {/*
              Force-mounted and hidden with the `hidden` attribute rather than unmounted, so the
              `aria-controls` above always resolves to a real element — the same arrangement the
              board's `TeamCard` uses. The *contents* are still mounted lazily, so a page of
              collapsed cards carries no hidden asset rows.
            */}
            <CollapsibleContent id={panelId} forceMount hidden={!open}>
              {open ? (
                <ul className="mt-2 space-y-1 border-t pt-2">
                  {trade.assets.map((asset, index) => (
                    <li key={`${asset.kind}-${index}`} className="text-sm">
                      {assetLabel(asset)}
                    </li>
                  ))}
                  {trade.assets.length === 0 && (
                    <li className="text-sm text-muted-foreground">
                      {NO_ASSETS_TEXT}
                    </li>
                  )}
                </ul>
              ) : null}
            </CollapsibleContent>
          </Collapsible>
        </CardContent>
      </Card>
    </li>
  );
}
