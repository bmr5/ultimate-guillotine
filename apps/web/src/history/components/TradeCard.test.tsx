import { fireEvent, render, screen } from "@testing-library/react";
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
  announcement: null,
  confidence: "low",
  registeredAt: null,
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 1,
};

/** The same deal as the Registrar recorded it, stamped and coded. */
const REGISTERED: CatalogTrade = {
  ...TRADE,
  key: "registered:5",
  confidence: "high",
  registeredAt: "2026-09-10T01:12:00Z",
  sourceLabel: "T-2026-014",
  registered: true,
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

  // Ben's ruling of 2026-09-09 cut the sublabel to the category alone: `2 team` was never a
  // category, only a restatement of the title, which already names every party in the deal.
  it("puts the category alone in a sublabel under the title", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.getByText("Rental")).toBeInTheDocument();
    expect(screen.queryByText(/player for FAAB/i)).not.toBeInTheDocument();
    expect(screen.getByText("Season 2024 · Week 3")).toBeInTheDocument();
  });

  // A row with no category at all gets no sublabel — not an empty muted line between the title
  // and the date, which reads as a caption the page failed to print.
  it("drops the sublabel when the row carries no trade type", () => {
    render(<TradeCard trade={{ ...TRADE, tradeType: "" }} />);
    const title = screen.getByText("Alpha ↔ a former manager");
    expect(title.nextElementSibling).toHaveTextContent("Season 2024 · Week 3");
  });

  it("dates a trade the catalog placed by date rather than by week", () => {
    render(
      <TradeCard trade={{ ...TRADE, week: null, occurredOn: "2024-09-30" }} />,
    );
    expect(screen.getByText("Season 2024 · 2024-09-30")).toBeInTheDocument();
  });

  // Ben's ruling: a card logs "the Participants, the date and time, a category, and the exact
  // text". A registered trade knows the instant it was recorded, so that is its date line. The
  // exact wording is the viewer's own locale's and is pinned in `tradeDate.test.ts`; what this
  // test owes is that the card reads the stamp at all rather than the season beside it.
  it("dates a registered card by the instant it was recorded", () => {
    render(<TradeCard trade={REGISTERED} />);
    expect(screen.queryByText("Season 2024 · Week 3")).not.toBeInTheDocument();
    expect(screen.getByText(/2026.*·/)).toBeInTheDocument();
  });

  // Ben's ruling: "$30 FAAB is wrong ... because of the dynamic nature of many deals it's most
  // likely not useful to include the FAAB number here". The fixture's assets carry 12 FAAB, so
  // a card that still totalled or listed them would say so somewhere.
  it("says nothing about FAAB, open or closed", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.queryByText(/FAAB/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /alpha/i }));
    expect(screen.queryByText(/FAAB/i)).not.toBeInTheDocument();
  });

  // The analyst's doubt is not one of the four things a card logs, and the fixture is a
  // low-confidence catalog row.
  it("does not badge a low-confidence catalog row", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.queryByText(/low confidence/i)).not.toBeInTheDocument();
  });

  // `catalog` says where the page read the deal, not anything about the deal, so it is not a
  // chip. A catalog trade that was not rescinded therefore carries no chips at all.
  it("carries no chips on a plain catalog row", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.queryByText("catalog")).not.toBeInTheDocument();
  });

  it("shows the trade code for a registered row and strikes a rescinded one", () => {
    render(<TradeCard trade={{ ...REGISTERED, rescinded: true }} />);
    expect(screen.getByText("T-2026-014")).toBeInTheDocument();
    expect(screen.getByText("Rescinded")).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveAttribute(
      "data-rescinded",
      "true",
    );
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

  // Ben's ruling of 2026-09-09 took the asset list off the expanded card. Opening one is now
  // exactly "show me the rest of what was said", so the panel holds the announcement and there
  // is no list of players and amounts under it.
  it("expands to the whole announcement and to no asset list", () => {
    render(
      <TradeCard trade={{ ...TRADE, announcement: "ANNOUNCEMENT-ONE" }} />,
    );
    const toggle = screen.getByRole("button", { name: /alpha/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByText(/A Player/)).not.toBeInTheDocument();
  });

  // The panel the toggle names has to exist even when the row carries nothing to put in it, or
  // `aria-controls` points at nothing and a screen reader is told about a region it cannot find.
  it("always points aria-controls at a real element", () => {
    const { container } = render(
      <TradeCard trade={{ ...TRADE, announcement: null }} />,
    );
    const panelId = screen
      .getByRole("button", { name: /alpha/i })
      .getAttribute("aria-controls");
    expect(panelId).not.toBeNull();
    expect(
      container.querySelector(`#${CSS.escape(panelId ?? "")}`),
    ).not.toBeNull();
  });
});
