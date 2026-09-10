import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TRADES_LOADING_LABEL } from "@/history/components/TradesSkeleton";

import { TradesPage } from "./TradesPage";

const trades = vi.hoisted(() => ({ value: [] as unknown[] }));
/** What `nfl_state` says the season is; 2025 matches the newer of the two trades below. */
const currentSeason = vi.hoisted(() => ({
  season: 2025 as number | null,
  isPending: false,
}));

vi.mock("@/history/useTradeCatalog", () => ({
  useTradeCatalog: () => ({
    trades: trades.value,
    replacedByBackfill: 1,
    loadedAt: Date.parse("2026-09-09T12:00:00Z"),
    // Deliberately not in label order, and not in id order either: the page has to sort the
    // owner options itself for the test below to mean anything.
    members: [
      { id: 1, nickname: "Zulu", sleeper_display_name: null },
      { id: 2, nickname: "Alpha", sleeper_display_name: null },
    ],
    isPending: false,
    errors: [],
  }),
}));

vi.mock("@/history/useCurrentSeason", () => ({
  useCurrentSeason: () => ({
    season: currentSeason.season,
    isPending: currentSeason.isPending,
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
  currentSeason.season = 2025;
  currentSeason.isPending = false;
  trades.value = [
    {
      key: "k1",
      season: 2025,
      week: 1,
      occurredOn: null,
      tradeType: "trade",
      structure: "1-for-1",
      parties: [
        { memberId: 1, label: "Zulu", resolved: true },
        { memberId: 2, label: "Alpha", resolved: true },
      ],
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
      ],
      confidence: "high",
      announcement: "ANNOUNCEMENT-ONE",
      registeredAt: null,
      announcedBy: null,
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
      confidence: "high",
      announcement: null,
      registeredAt: null,
      announcedBy: null,
      sourceLabel: "catalog",
      registered: false,
      rescinded: false,
      unresolvedParties: 2,
    },
  ];
});

describe("TradesPage", () => {
  // Ben's ruling of 2026-09-09: the page opens on the current season. Twenty years of catalog
  // is the answer to a question nobody arriving from the board asked.
  it("opens on the current season's trades and the stats strip", () => {
    renderPage();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/2025 · Week 1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "2025" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Trades").nextSibling).toHaveTextContent("1");
    expect(
      screen.getByText(/1 earlier catalog reading replaced/),
    ).toBeInTheDocument();
  });

  it("shows every season when the URL asks for all", () => {
    renderPage("/trades?season=all");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("writes the All chip into the query string rather than dropping the param", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    // An absent param means the default, which is the current season; "all" has to be said.
    expect(currentSearch()).toBe("?season=all");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("offers the current season as a chip before it has any trades", () => {
    currentSeason.season = 2026;
    renderPage();
    const chips = screen.getByRole("group", { name: "Season" });
    expect(
      [...chips.querySelectorAll("button")].map((chip) => chip.textContent),
    ).toEqual(["All", "2026", "2025", "2024"]);
    expect(screen.getByRole("button", { name: "2026" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(
      screen.getByText("No trades match these filters."),
    ).toBeInTheDocument();
  });

  it("offers every season from an empty current season", () => {
    currentSeason.season = 2026;
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "All seasons" }));
    expect(currentSearch()).toBe("?season=all");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("holds the skeleton until the current season is known", () => {
    currentSeason.season = null;
    currentSeason.isPending = true;
    renderPage();
    // Showing every season and then narrowing to one a moment later would flash twenty years
    // of trades past the reader; a URL that names its own season has nothing to wait for.
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.queryByText(/No trades/)).not.toBeInTheDocument();
    // And says so: a page of grey blocks with no word on them reads as frozen, not loading.
    expect(
      screen.getByRole("status", { name: TRADES_LOADING_LABEL }),
    ).toBeInTheDocument();
  });

  it("shows every season when the current one cannot be read", () => {
    currentSeason.season = null;
    renderPage();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("does not wait for the current season when the URL names one", () => {
    currentSeason.season = null;
    currentSeason.isPending = true;
    renderPage("/trades?season=2024");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  // Ben's ruling of 2026-09-09: "because of the dynamic nature of many deals it's most likely
  // not useful to include the FAAB number here". The strip is where the last FAAB figure on
  // the page lived, and its footnote with it.
  it("says nothing about FAAB in the stats strip", () => {
    renderPage();
    expect(screen.queryByText(/FAAB/i)).not.toBeInTheDocument();
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
    // Back to the defaults, which is the current season — not to every season.
    expect(currentSearch()).toBe("");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("names the trade list", () => {
    renderPage();
    // A screen reader announces an unlabelled list by its length alone, and this page carries
    // more than one list — the filter bar's owner select is not one, but the strip beside it
    // and any list a future card grows would be.
    expect(screen.getByRole("list", { name: "Trades" })).toBeInTheDocument();
  });

  it("sorts the owner options by label, not by member id", () => {
    renderPage();
    const owners = screen.getByLabelText("Owner");
    expect(
      [...owners.querySelectorAll("option")].map(
        (option) => option.textContent,
      ),
    ).toEqual(["Any owner", "Alpha", "Zulu"]);
  });

  // Ben's ruling: the filter never lists a former manager. One "Former manager" option would
  // stand for every unmapped party in the catalog at once, so picking it would gather
  // strangers into a single owner's view.
  it("leaves an owner it cannot name out of the filter", () => {
    const base = trades.value[0] as Record<string, unknown>;
    trades.value = [
      ...trades.value,
      {
        ...base,
        key: "k3",
        parties: [{ memberId: 3, label: "Former manager", resolved: false }],
      },
    ];
    renderPage();
    expect(
      [...screen.getByLabelText("Owner").querySelectorAll("option")].map(
        (option) => option.textContent,
      ),
    ).toEqual(["Any owner", "Alpha", "Zulu"]);
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
