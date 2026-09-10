import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import { formerManagerPhrase } from "../derive/ownerLabel";
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

/**
 * What sits between two owners in the title. A trade goes both ways, so the arrow does too —
 * "Derek → Charlie" would name a direction the row does not record.
 */
const OWNER_SEPARATOR = " ↔ ";

/**
 * `flat_fee_rental` and `player-for-faab` into words, with FAAB kept as the initialism it is.
 *
 * The analyst's taxonomy is snake_case and the Registrar's is hyphenated, and neither was
 * written to be read aloud. Only the separators change: the vocabulary is still his, so a term
 * this function has never seen comes out as its own words rather than as a category it was
 * mapped onto.
 */
function words(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\bfaab\b/gi, "FAAB");
}

/**
 * The sublabel Ben asked for: the category, then the structure, in sentence case.
 *
 * Sentence case rather than title case because it is a caption under a title, not a second
 * title — "Rental · player for FAAB" reads as a description of the deal above it, where
 * "Rental · Player For FAAB" reads as a heading competing with one.
 */
function categoryLabel(trade: CatalogTrade): string {
  // Joined from the parts that exist rather than interpolated, and capitalised after the
  // filter rather than before it. A row carrying no `trade_type` would otherwise open its
  // sublabel with a bare " · ", which reads as a category the page failed to print rather than
  // as one the row never carried — and then lead with a lowercase word where the caption is
  // supposed to start with a capital one.
  const parts = [words(trade.tradeType), words(trade.structure)].filter(
    (part) => part !== "",
  );
  return parts
    .map((part, index) =>
      index === 0 ? `${part.charAt(0).toUpperCase()}${part.slice(1)}` : part,
    )
    .join(" · ");
}

/** `Season 2024 · Week 3`, or the date when the catalog placed the trade by date instead. */
function whenLabel(trade: CatalogTrade): string {
  if (trade.week !== null) return `Season ${trade.season} · Week ${trade.week}`;
  if (trade.occurredOn !== null)
    return `Season ${trade.season} · ${trade.occurredOn}`;
  return `Season ${trade.season}`;
}

/**
 * The card's title: the people in the deal, in the order the trade lists them.
 *
 * Ben's ruling: "the titles are dumb … I would prefer the category be shown in like a sublabel
 * and trade named between the owners". So a card is named the way the league names a trade in
 * conversation — by who was in it.
 *
 * The parties the page could not name are one trailing segment rather than one segment each:
 * "Alpha ↔ 2 former managers" is what the row actually knows, where "Alpha ↔ a former manager ↔
 * a former manager" reads as two identified people who happen to share a name. The wording is
 * `formerManagerPhrase`'s.
 *
 * Both kinds of unnamed party fold into that one count, which is why the title reads
 * `party.resolved` rather than the length of the array: a party missing from `party_member_ids`
 * altogether never reaches `parties`, but one whose recorded id resolves to no member does, and
 * it arrives carrying `FORMER_MANAGER`. Naming it with the rest would put that capitalised
 * stand-in mid-title, once per head — the very reading the fold exists to refuse.
 *
 * Empty when the row names nobody at all — the caller falls back to the category rather than
 * hanging an empty heading on the card.
 */
function ownersTitle(trade: CatalogTrade): string {
  const segments = trade.parties
    .filter((party) => party.resolved)
    .map((party) => party.label);
  const unnamed = Math.max(trade.partyCount - segments.length, 0);
  if (unnamed > 0) segments.push(formerManagerPhrase(unnamed));
  return segments.join(OWNER_SEPARATOR);
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
  const category = categoryLabel(trade);
  const owners = ownersTitle(trade);

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
                <span
                  className={cn(
                    "block truncate text-sm font-medium",
                    trade.rescinded && "line-through",
                  )}
                >
                  {/* A trade whose parties were never recorded has no owners to be named
                      between, so it keeps the heading the card used to carry rather than an
                      empty one — and then the sublabel below would only repeat it. */}
                  {owners === "" ? category : owners}
                </span>
                {owners !== "" && (
                  <span className="block text-xs text-muted-foreground">
                    {category}
                  </span>
                )}
                <span className="block text-xs text-muted-foreground">
                  {whenLabel(trade)}
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

            {/*
              Ben's ruling: "include the actual text of the trade to give more context, it is
              hard to understand these tiles". A <blockquote>, because it is somebody else's
              words and not the page's, and `whitespace-pre-line` so two messages stay two
              paragraphs — the loader joined them with a blank line for exactly that.

              Clamped to four lines while the card is collapsed and whole once it is open, so a
              long announcement cannot turn one card in a grid of them into a wall of text. It
              sits outside the button on purpose: a quotation is not part of the toggle's
              accessible name, and a <blockquote> inside a <button> is not valid markup either.

              `null` renders nothing at all. An empty quote block would say the league said
              nothing, when what happened is that this row carries nothing.
            */}
            {trade.announcement !== null && (
              <blockquote
                className={cn(
                  "mt-2 border-l-2 pl-2 text-xs whitespace-pre-line text-muted-foreground",
                  !open && "line-clamp-4",
                )}
              >
                {trade.announcement}
              </blockquote>
            )}

            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {/* The owners are the title now, so they are not also badges. What is left here
                  is everything the title does not say: the money, the analyst's doubt, and the
                  two chips Ben kept — the rescinded mark and the trade code. */}
              {trade.faabTotal !== null && (
                <Badge
                  variant="outline"
                  className="border-primary/40 text-primary"
                >
                  {trade.faabTotal} FAAB
                </Badge>
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
