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
  parties: [{ memberId: 1, label: "Alpha" }],
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
  confidence: "low",
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 1,
};

describe("TradeCard", () => {
  it("names the resolved owner and counts the one it could not", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText(/and 1 unidentified owner/i)).toBeInTheDocument();
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
