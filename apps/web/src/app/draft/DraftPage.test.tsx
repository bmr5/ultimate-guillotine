import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DRAFT_LOADING_LABEL } from "@/draft/components/DraftSkeleton";
import type { DraftPageData } from "@/draft/useDraftPage";

import { DraftPage, NO_DRAFT_LABEL } from "./DraftPage";

const data = vi.hoisted(() => ({ current: null as DraftPageData | null }));

vi.mock("@/draft/useDraftPage", () => ({
  useDraftPage: () => data.current,
}));

const DRAFTED_AT = "2026-09-07T23:01:30Z";

const result = (over: Partial<DraftPageData> = {}): DraftPageData => ({
  season: 2026,
  waiverBudget: 1000,
  picks: [
    { team_id: 11, sleeper_player_id: "9493", pick_no: 1, round: 1, position: "WR", amount: 53, drafted_at: DRAFTED_AT },
    { team_id: 3, sleeper_player_id: "4046", pick_no: 2, round: 1, position: "QB", amount: 45, drafted_at: DRAFTED_AT },
    { team_id: 11, sleeper_player_id: "1111", pick_no: 3, round: 1, position: "RB", amount: 60, drafted_at: DRAFTED_AT },
  ],
  teams: [
    { id: 11, sleeper_roster_id: 1, team_name: "Ray Regime", member_id: 101 },
    { id: 3, sleeper_roster_id: 2, team_name: "chobes", member_id: 103 },
  ],
  members: [
    { id: 101, sleeper_display_name: "jrayay", nickname: "Jesse" },
    { id: 103, sleeper_display_name: "chobes", nickname: null },
  ],
  players: [
    { sleeper_player_id: "9493", full_name: "Puka Nacua", position: "WR", team: "LAR", injury_status: null },
    { sleeper_player_id: "4046", full_name: "Patrick Mahomes", position: "QB", team: "KC", injury_status: null },
    { sleeper_player_id: "1111", full_name: "Bijan Robinson", position: "RB", team: "ATL", injury_status: null },
  ],
  isPending: false,
  errors: [],
  refetchAll: vi.fn(),
  ...over,
});

function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">{`${location.pathname}${location.search}`}</div>
  );
}

function renderPage(initialEntry = "/draft") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DraftPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DraftPage", () => {
  beforeEach(() => {
    data.current = result();
  });

  it("says what is loading", () => {
    data.current = result({ isPending: true, picks: [] });
    renderPage();
    expect(
      screen.getByRole("status", { name: DRAFT_LOADING_LABEL }),
    ).toBeInTheDocument();
  });

  it("says there is no draft yet when the season has no picks", () => {
    data.current = result({ picks: [] });
    renderPage();
    expect(screen.getByText(NO_DRAFT_LABEL)).toBeInTheDocument();
  });

  it("lists every pick in pick order, with the price and the owner, and links each name to the board", () => {
    renderPage();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("1");
    expect(items[0]).toHaveTextContent("Puka Nacua");
    expect(items[0]).toHaveTextContent("WR · LAR");
    expect(items[0]).toHaveTextContent("$53");
    expect(items[0]).toHaveTextContent("Jesse");
    expect(
      within(items[0]).getByRole("link", { name: "Puka Nacua" }),
    ).toHaveAttribute("href", "/?player=9493");
    expect(items[2]).toHaveTextContent("Bijan Robinson");
  });

  it("sums the auction in the strip", () => {
    renderPage();
    // Scoped to the strip: a pick number can spell the same digit further down the page.
    const cell = (label: string) =>
      screen.getByText(label).parentElement as HTMLElement;
    expect(within(cell("Picks")).getByText("3")).toBeInTheDocument();
    expect(within(cell("Spent")).getByText("$158")).toBeInTheDocument();
    expect(within(cell("Average")).getByText("$53")).toBeInTheDocument();
  });

  it("sorts by price and writes the sort into the URL", () => {
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: "Price" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/draft?sort=price");
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Bijan Robinson");
  });

  it("groups by team with each team's spend and its unspent dollars as FAAB", () => {
    renderPage("/draft?sort=team");
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings[0]).toHaveTextContent("Jesse");
    expect(headings[0]).toHaveTextContent("$113 spent");
    expect(headings[0]).toHaveTextContent("$87 unspent → $435 FAAB");
    expect(headings[1]).toHaveTextContent("chobes");
  });

  it("names a failed section and keeps the list", () => {
    data.current = result({
      errors: [{ section: "Players", message: "network down" }],
    });
    renderPage();
    expect(screen.getByText("Players could not load")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").length).toBe(3);
  });
});
