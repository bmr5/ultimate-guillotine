import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TradesPage } from "./TradesPage";

const trades = vi.hoisted(() => ({ value: [] as unknown[] }));

vi.mock("@/history/useTradeCatalog", () => ({
  useTradeCatalog: () => ({
    trades: trades.value,
    replacedByBackfill: 1,
    loadedAt: Date.parse("2026-09-09T12:00:00Z"),
    members: [{ id: 1, nickname: "Alpha", sleeper_display_name: null }],
    isPending: false,
    errors: [],
  }),
}));

/** The live query string, so a test can assert what a control wrote into the URL. */
function LocationProbe() {
  return <span data-testid="search">{useLocation().search}</span>;
}

function currentSearch(): string {
  return screen.getByTestId("search").textContent ?? "";
}

function renderPage(initialEntry = "/trades") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <TradesPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  trades.value = [
    {
      key: "k1",
      season: 2025,
      week: 1,
      occurredOn: null,
      tradeType: "trade",
      structure: "1-for-1",
      parties: [{ memberId: 1, label: "Alpha" }],
      partyCount: 1,
      assets: [
        {
          kind: "player",
          playerId: "1",
          name: "A Player",
          position: "RB",
          fromParty: 0,
          toParty: 1,
        },
      ],
      faabTotal: 4,
      confidence: "high",
      sourceLabel: "catalog",
      registered: false,
      rescinded: false,
      unresolvedParties: 0,
    },
    {
      key: "k2",
      season: 2024,
      week: 2,
      occurredOn: null,
      tradeType: "rental",
      structure: "player-for-faab",
      parties: [],
      partyCount: 2,
      assets: [],
      faabTotal: null,
      confidence: "high",
      sourceLabel: "catalog",
      registered: false,
      rescinded: false,
      unresolvedParties: 2,
    },
  ];
});

describe("TradesPage", () => {
  it("renders every trade and the stats strip", () => {
    renderPage();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("FAAB moved").nextSibling).toHaveTextContent("4");
    expect(
      screen.getByText(/1 earlier catalog reading replaced/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("FAAB moved excludes rescinded trades"),
    ).toBeInTheDocument();
  });

  it("filters by the season in the URL", () => {
    renderPage("/trades?season=2024");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/2024 · Week 2/)).toBeInTheDocument();
  });

  it("says so when a filter matches nothing", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Search players"), {
      target: { value: "zzz" },
    });
    expect(
      await screen.findByText("No trades match these filters."),
    ).toBeInTheDocument();
  });

  it("shows the empty state when nothing is loaded", () => {
    trades.value = [];
    renderPage();
    expect(screen.getByText("No trades loaded yet.")).toBeInTheDocument();
  });

  it("writes a season chip into the query string", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "2024" }));
    expect(currentSearch()).toBe("?season=2024");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("clears this page's filters and leaves anything else in the URL alone", () => {
    renderPage(
      "/trades?season=2024&type=rental&pos=RB&owner=1&q=play&ref=slack",
    );
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    // Only the five filter params are this page's to remove; `ref` belongs to whoever linked
    // here and survives.
    expect(currentSearch()).toBe("?ref=slack");
  });

  it("offers a way out of the no-match state", async () => {
    renderPage("/trades?q=zzz");
    fireEvent.click(
      await screen.findByRole("button", { name: "Clear filters" }),
    );
    expect(currentSearch()).toBe("");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("shows a URL filter the loaded trades do not offer", () => {
    renderPage("/trades?pos=TE");
    // No trade on screen has a TE, so "TE" is not one of the derived options; without a
    // fallback the select would read "Any position" while a position filter was in force.
    const option = screen.getByRole("option", { name: "TE" });
    expect(option).toBeDisabled();
    expect(screen.getByLabelText("Position")).toHaveValue("TE");
    expect(
      screen.getByText("No trades match these filters."),
    ).toBeInTheDocument();
  });
});
