import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { formerManagerPhrase } from "../derive/ownerLabel";
import { tradeDateLine } from "../derive/tradeDate";
import type { CatalogTrade } from "../types";

/**
 * The focus ring every other bare `<button>` on the site carries (see `TeamCard`). This one is
 * not a `Button`, so it has to name the ring itself or it is a keyboard stop with no visible
 * focus at all.
 */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/** The chip on a trade the league undid. */
const RESCINDED_LABEL = "Rescinded";

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
 * The sublabel: the category, and only the category.
 *
 * It used to carry the structure as well (`Rental · player for FAAB`). Ben's ruling of
 * 2026-09-09 cut the card to "the Participants, the date and time, a category, and the exact
 * text", and `2 team` was never a category — it was a restatement of the title, which already
 * names every party in the deal.
 *
 * Sentence case rather than title case because it is a caption under a title, not a second
 * title: "Rental" reads as a description of the deal above it, where a heading-cased word reads
 * as a second heading competing with one. The empty string for a row carrying no category at
 * all, which the caller renders as no sublabel rather than as a blank line.
 */
function categoryLabel(trade: CatalogTrade): string {
  const category = words(trade.tradeType);
  if (category === "") return "";
  return `${category.charAt(0).toUpperCase()}${category.slice(1)}`;
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

export function TradeCard({ trade }: { trade: CatalogTrade }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const category = categoryLabel(trade);
  const owners = ownersTitle(trade);
  // The trade code is the registered row's own name for itself. A catalog row's `sourceLabel`
  // is the literal `catalog`, which Ben's ruling leaves off the card: it says where the page
  // read the deal, not anything about the deal.
  const chips = trade.rescinded || trade.registered;

  return (
    <li data-rescinded={trade.rescinded} className="list-none">
      <Card className={cn(trade.rescinded && "opacity-60")}>
        <CardContent className="p-3">
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
              {owners !== "" && category !== "" && (
                <span className="block text-xs text-muted-foreground">
                  {category}
                </span>
              )}
              <span className="block text-xs text-muted-foreground">
                {tradeDateLine(trade)}
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
            The panel the toggle above controls, and the whole of it: Ben's ruling of 2026-09-09
            took the asset list off the expanded card, so opening a card is now exactly "show me
            the rest of what was said". The wrapper is rendered unconditionally rather than with
            the quotation inside it, so `aria-controls` always resolves to a real element — the
            same guarantee the force-mounted collapsible used to give, without the collapsible.

            The quotation itself: a <blockquote>, because it is somebody else's words and not the
            page's, and `whitespace-pre-line` so two messages stay two paragraphs — the loader
            joined them with a blank line for exactly that. Clamped to four lines while the card
            is collapsed and whole once it is open, so a long announcement cannot turn one card
            in a grid of them into a wall of text.

            It sits outside the button on purpose: a quotation is not part of the toggle's
            accessible name, and a <blockquote> inside a <button> is not valid markup either.

            `null` renders nothing at all. An empty quote block would say the league said
            nothing, when what happened is that this row carries nothing.
          */}
          <div id={panelId}>
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
          </div>

          {/* The two chips Ben kept, and nothing else. The owners are the title now; the FAAB
              total and the analyst's confidence are both gone — "because of the dynamic nature
              of many deals it's most likely not useful to include the FAAB number here". */}
          {chips && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {trade.rescinded && (
                <Badge variant="destructive">{RESCINDED_LABEL}</Badge>
              )}
              {trade.registered && <Badge>{trade.sourceLabel}</Badge>}
            </div>
          )}
        </CardContent>
      </Card>
    </li>
  );
}
