import { Maximize2 } from "lucide-react";

import { ExplainedBadge } from "@/components/explained-badge";
import { badgeVariants } from "@/components/ui/badge-variants";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { announcedByLine } from "../derive/announcedBy";
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

/** The chip on a trade the league undid, and the sentence behind it. */
const RESCINDED_LABEL = "Rescinded";
const RESCINDED_DESCRIPTION =
  "The league undid this trade after it was recorded; it is kept for the record";

/** The sentence behind a registered trade's code. */
const TRADE_CODE_DESCRIPTION =
  "The Registrar's code for this trade, as it was recorded from the league chat";

/**
 * Every card is this tall, whatever it carries. Ben's ruling of 2026-09-09: "make sure all the
 * trade cards are the same size" — a grid where one tile is a title and the next is a wall of
 * quotation is not a grid. Room for the three header lines, a three-line quotation and a row
 * of chips; anything longer is what the modal is for.
 */
const CARD_HEIGHT_CLASS = "h-44";

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

/**
 * The two chips Ben kept, and nothing else; shared by the card and the modal. Each one says why
 * it is there (Ben's ruling of 2026-09-09: a tooltip on every badge). `relative z-10` lifts the
 * row above the card trigger's stretched hit area, or a tap on a chip would open the modal.
 */
function Chips({ trade }: { trade: CatalogTrade }) {
  if (!trade.rescinded && !trade.registered) return null;
  return (
    <div className="relative z-10 flex flex-wrap items-center gap-1.5">
      {trade.rescinded && (
        <ExplainedBadge
          description={RESCINDED_DESCRIPTION}
          className={badgeVariants({ variant: "destructive" })}
        >
          {RESCINDED_LABEL}
        </ExplainedBadge>
      )}
      {trade.registered && (
        <ExplainedBadge
          description={TRADE_CODE_DESCRIPTION}
          className={badgeVariants({ variant: "default" })}
        >
          {trade.sourceLabel}
        </ExplainedBadge>
      )}
    </div>
  );
}

/**
 * The modal, which is where a reader deep-dives (Ben's ruling of 2026-09-09: "expandable into a
 * scrollable modal view when a user wants to deep dive into it").
 *
 * It carries the same four things as the card — the participants, the date, the category and
 * the exact text — with the quotation whole and scrolling inside the modal, and the players the
 * deal moved come back here. The ruling that took the asset list off the *tile* was about the
 * tile: "it is hard to understand these tiles". The FAAB figure stays out everywhere: "because
 * of the dynamic nature of many deals it's most likely not useful to include the FAAB number".
 * A FAAB-only deal therefore lists no players, and the heading goes with them.
 */
function TradeDetail({
  trade,
  title,
  category,
}: {
  trade: CatalogTrade;
  title: string;
  category: string;
}) {
  const players = trade.assets.filter((asset) => asset.kind === "player");
  const conditions = trade.assets.filter((asset) => asset.kind === "condition");
  const description = [category, tradeDateLine(trade), announcedByLine(trade)]
    .filter((line) => line !== "")
    .join(" · ");
  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle className={cn(trade.rescinded && "line-through")}>
          {title}
        </DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>

      {/* The one child allowed to scroll: `min-h-0` lets the flex column hand it whatever
          height is left under the header and above the chips, instead of it sizing to the
          quotation and pushing the rest off the screen. */}
      <div className="min-h-0 space-y-4 overflow-y-auto">
        {trade.announcement !== null && (
          <blockquote className="border-l-2 pl-3 text-sm whitespace-pre-line text-muted-foreground">
            {trade.announcement}
          </blockquote>
        )}
        {players.length > 0 && (
          <section>
            <h3 className="text-xs font-medium text-muted-foreground">
              Players
            </h3>
            <ul className="mt-1 space-y-0.5 text-sm">
              {players.map((asset, index) => (
                <li key={`${asset.playerId ?? asset.name}-${index}`}>
                  {asset.name}
                  {asset.position !== null && (
                    <span className="text-muted-foreground">
                      {" "}
                      · {asset.position}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
        {conditions.length > 0 && (
          <section>
            <h3 className="text-xs font-medium text-muted-foreground">
              Conditions
            </h3>
            <ul className="mt-1 space-y-0.5 text-sm">
              {conditions.map((asset, index) => (
                <li key={index}>{words(asset.label)}</li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <Chips trade={trade} />
    </DialogContent>
  );
}

export function TradeCard({ trade }: { trade: CatalogTrade }) {
  const category = categoryLabel(trade);
  const owners = ownersTitle(trade);
  // A trade whose parties were never recorded has no owners to be named between, so it keeps
  // the heading the card used to carry rather than an empty one — and then the sublabel below
  // would only repeat it.
  const title = owners === "" ? category : owners;

  return (
    <li data-rescinded={trade.rescinded} className="list-none">
      <Dialog>
        {/* `relative` so the trigger's stretched hit area below is the card and not the page. */}
        <Card
          className={cn(
            "relative flex flex-col",
            CARD_HEIGHT_CLASS,
            trade.rescinded && "opacity-60",
          )}
        >
          <CardContent className="flex min-h-0 flex-1 flex-col overflow-hidden p-3">
            {/*
              The header is the trigger, and its `after:` pseudo-element is stretched over the
              whole card so the quotation below is clickable too — without the quotation being
              *inside* the button, where a <blockquote> is not valid markup and somebody else's
              words would become part of the toggle's accessible name.
            */}
            <DialogTrigger asChild>
              <button
                type="button"
                className={cn(
                  "flex w-full items-start justify-between gap-2 text-left after:absolute after:inset-0 after:rounded-xl",
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
                    {title}
                  </span>
                  {owners !== "" && category !== "" && (
                    <span className="block truncate text-xs text-muted-foreground">
                      {category}
                    </span>
                  )}
                  <span className="block truncate text-xs text-muted-foreground">
                    {[tradeDateLine(trade), announcedByLine(trade)]
                      .filter((line) => line !== "")
                      .join(" · ")}
                  </span>
                </span>
                <Maximize2
                  aria-hidden
                  className="mt-1 h-4 w-4 shrink-0 text-muted-foreground"
                />
              </button>
            </DialogTrigger>

            {/*
              The quotation: a <blockquote>, because it is somebody else's words and not the
              page's, and `whitespace-pre-line` so two messages stay two paragraphs — the loader
              joined them with a blank line for exactly that. Clamped to three lines so a long
              announcement cannot turn one card in a grid of them into a wall of text; the whole
              of it is in the modal.

              `null` renders nothing at all. An empty quote block would say the league said
              nothing, when what happened is that this row carries nothing.
            */}
            {trade.announcement !== null && (
              <blockquote className="mt-2 line-clamp-3 border-l-2 pl-2 text-xs whitespace-pre-line text-muted-foreground">
                {trade.announcement}
              </blockquote>
            )}

            {/* Pinned to the bottom, so a card without a quotation keeps its chips where every
                other card has them. */}
            <div className="mt-auto pt-2 empty:hidden">
              <Chips trade={trade} />
            </div>
          </CardContent>
        </Card>

        <TradeDetail trade={trade} title={title} category={category} />
      </Dialog>
    </li>
  );
}
