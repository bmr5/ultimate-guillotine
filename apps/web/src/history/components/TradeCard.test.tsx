import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CatalogTrade } from "../types";
import { TradeCard } from "./TradeCard";

const TRADE: CatalogTrade = {
  key: "catalog:1",
  season: 2024,
  week: 3,
  occurredOn: null,
  tradeType: "rental",
  structure: "player-for-faab",
  parties: [{ memberId: 1, label: "Alpha", resolved: true }],
  partyCount: 2,
  assets: [
    {
      kind: "player",
      playerId: "1",
      name: "A Player",
      position: "RB",
      fromParty: 0,
      toParty: 1,
    },
    { kind: "faab", amount: 12, fromParty: 1, toParty: 0 },
    { kind: "condition", label: "rental" },
  ],
  faabTotal: 12,
  announcement: null,
  confidence: "low",
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 1,
};

describe("TradeCard", () => {
  // Ben's ruling: "the titles are dumb ... I would prefer the category be shown in like a
  // sublabel and trade named between the owners". So the card is named by who was in the deal.
  it("names the trade between its owners", () => {
    render(
      <TradeCard
        trade={{
          ...TRADE,
          parties: [
            { memberId: 1, label: "Alpha", resolved: true },
            { memberId: 2, label: "Bravo", resolved: true },
          ],
          partyCount: 2,
          unresolvedParties: 0,
        }}
      />,
    );
    expect(screen.getByText("Alpha ↔ Bravo")).toBeInTheDocument();
  });

  it("names a three-way trade between all three", () => {
    render(
      <TradeCard
        trade={{
          ...TRADE,
          parties: [
            { memberId: 1, label: "Alpha", resolved: true },
            { memberId: 2, label: "Bravo", resolved: true },
            { memberId: 3, label: "Charlie", resolved: true },
          ],
          partyCount: 3,
          unresolvedParties: 0,
        }}
      />,
    );
    expect(screen.getByText("Alpha ↔ Bravo ↔ Charlie")).toBeInTheDocument();
  });

  // The other half of Ben's ruling, from the former-members branch: a party the page cannot
  // name is a manager who has left, not a failure to identify one.
  it("names an owner it could not resolve as a former manager", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.getByText("Alpha ↔ a former manager")).toBeInTheDocument();
    expect(screen.queryByText(/unidentified/i)).not.toBeInTheDocument();
  });

  // One segment, not one per head: "Alpha ↔ a former manager ↔ a former manager" would read as
  // two identified people who happen to share a name.
  it("counts two or more of them into one segment of the title", () => {
    render(
      <TradeCard trade={{ ...TRADE, partyCount: 4, unresolvedParties: 3 }} />,
    );
    expect(screen.getByText("Alpha ↔ 3 former managers")).toBeInTheDocument();
  });

  // The recorded-id case, which the count used to miss: the id reached `parties` and arrived
  // carrying `FORMER_MANAGER`, so the old title named it with the rest — "Alpha ↔ Former
  // manager ↔ Former manager", capitalised and mid-sentence, one segment per head.
  it("folds a recorded party the directory cannot name into the count", () => {
    render(
      <TradeCard
        trade={{
          ...TRADE,
          parties: [
            { memberId: 1, label: "Alpha", resolved: true },
            { memberId: 98, label: "Former manager", resolved: false },
            { memberId: 99, label: "Former manager", resolved: false },
          ],
          partyCount: 3,
          unresolvedParties: 0,
        }}
      />,
    );
    expect(screen.getByText("Alpha ↔ 2 former managers")).toBeInTheDocument();
    expect(screen.queryByText(/Former manager/)).not.toBeInTheDocument();
  });

  // One of each kind of unnamed party. They are the same fact to a reader — a head the page
  // cannot put a name to — so they are one count, not two segments.
  it("counts a party it could not resolve and one never recorded together", () => {
    render(
      <TradeCard
        trade={{
          ...TRADE,
          parties: [
            { memberId: 1, label: "Alpha", resolved: true },
            { memberId: 99, label: "Former manager", resolved: false },
          ],
          partyCount: 3,
          unresolvedParties: 1,
        }}
      />,
    );
    expect(screen.getByText("Alpha ↔ 2 former managers")).toBeInTheDocument();
  });

  it("puts the category and the structure in a sublabel under the title", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.getByText("Rental · player for FAAB")).toBeInTheDocument();
    expect(screen.getByText("Season 2024 · Week 3")).toBeInTheDocument();
  });

  // A row with no category at all: the sublabel is the structure alone, not " · 1-for-1" with
  // a separator hanging off the front of it.
  it("drops the separator when the row carries no trade type", () => {
    render(<TradeCard trade={{ ...TRADE, tradeType: "" }} />);
    expect(screen.getByText("Player for FAAB")).toBeInTheDocument();
    expect(screen.queryByText(/^·/)).not.toBeInTheDocument();
  });

  it("dates a trade the catalog placed by date rather than by week", () => {
    render(
      <TradeCard trade={{ ...TRADE, week: null, occurredOn: "2024-09-30" }} />,
    );
    expect(screen.getByText("Season 2024 · 2024-09-30")).toBeInTheDocument();
  });

  it("badges a low-confidence catalog row", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.getByText(/low confidence/i)).toBeInTheDocument();
    expect(screen.getByText("catalog")).toBeInTheDocument();
  });

  it("shows the trade code for a registered row and strikes a rescinded one", () => {
    render(
      <TradeCard
        trade={{
          ...TRADE,
          sourceLabel: "T-2025-014",
          registered: true,
          rescinded: true,
          confidence: "high",
          unresolvedParties: 0,
        }}
      />,
    );
    expect(screen.getByText("T-2025-014")).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveAttribute(
      "data-rescinded",
      "true",
    );
    expect(screen.queryByText(/low confidence/i)).not.toBeInTheDocument();
  });

  // Ben's ruling: "include the actual text of the trade to give more context, it is hard to
  // understand these tiles". Every announcement in these fixtures is invented.
  it("quotes the announcement, clamped until the card is opened", () => {
    render(
      <TradeCard
        trade={{
          ...TRADE,
          announcement: "ANNOUNCEMENT-ONE\n\nANNOUNCEMENT-TWO",
        }}
      />,
    );
    const quote = screen.getByText(/ANNOUNCEMENT-ONE/);
    expect(quote.tagName).toBe("BLOCKQUOTE");
    // Two messages stay two paragraphs rather than running together.
    expect(quote).toHaveClass("whitespace-pre-line");
    expect(quote).toHaveClass("line-clamp-4");
    expect(quote).toHaveTextContent("ANNOUNCEMENT-TWO");

    fireEvent.click(screen.getByRole("button", { name: /alpha/i }));
    expect(screen.getByText(/ANNOUNCEMENT-ONE/)).not.toHaveClass(
      "line-clamp-4",
    );
  });

  it("renders nothing at all for a trade with no announcement", () => {
    const { container } = render(
      <TradeCard trade={{ ...TRADE, announcement: null }} />,
    );
    expect(container.querySelector("blockquote")).toBeNull();
  });

  // The quotation is somebody else's words, not a label for the toggle, so it stays out of the
  // button's accessible name — and a <blockquote> inside a <button> is not valid markup either.
  it("keeps the announcement out of the toggle's accessible name", () => {
    render(
      <TradeCard trade={{ ...TRADE, announcement: "ANNOUNCEMENT-ONE" }} />,
    );
    expect(
      screen.getByRole("button", { name: /alpha/i }),
    ).not.toHaveTextContent("ANNOUNCEMENT-ONE");
  });

  it("expands to the asset list", () => {
    render(<TradeCard trade={TRADE} />);
    const toggle = screen.getByRole("button", { name: /rental/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    // Scoped to the asset list, and matched by regex rather than by an exact string. An asset
    // row that knows the position renders "A Player (RB)", and the FAAB total badge in the
    // summary carries the same "12 FAAB" wording as the asset row it totals, so an unscoped
    // `getByText` finds two elements.
    const assets = within(screen.getByRole("list"));
    expect(assets.getByText(/A Player/)).toBeInTheDocument();
    expect(assets.getByText(/12 FAAB/)).toBeInTheDocument();
  });
});
