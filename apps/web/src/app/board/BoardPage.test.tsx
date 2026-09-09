import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MS_PER_MINUTE, STALE_AFTER_MS } from "@/board/derive/time";
import type { BoardTeam, RosterPlayer } from "@/board/types";
import type { BoardDataResult } from "@/board/useBoardData";

import { BoardPage } from "./BoardPage";

const boardData = vi.hoisted(() => ({
  current: null as BoardDataResult | null,
}));
const realtime = vi.hoisted(() => ({
  isConnected: true,
  hasConnectedOnce: true,
  refreshNow: vi.fn(),
}));

vi.mock("@/board/useBoardData", () => ({
  useBoardData: () => boardData.current,
}));

vi.mock("@/board/useLeagueBoardRealtime", () => ({
  useLeagueBoardRealtime: () => ({
    isConnected: realtime.isConnected,
    hasConnectedOnce: realtime.hasConnectedOnce,
    reconnectAttempts: 0,
    refreshNow: realtime.refreshNow,
  }),
}));

const PAUSED_BANNER_TEXT = "Live updates are paused. Polling every 60 seconds.";
const SEARCH_LABEL = "Search owner, team, or player";

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  isRosterFrozen: false,
  teamName: `Team ${over.teamId}`,
  ownerName: `owner${over.teamId}`,
  sleeperRosterId: over.teamId,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: "2026-09-09T12:00:00Z",
  faabRemaining: 50,
  pointsFor: 100,
  startersProjected: 9,
  starterSlots: 9,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  emptySlots: null,
  roster: [],
  ...over,
});

const player = (
  over: Partial<RosterPlayer> & { sleeperPlayerId: string; fullName: string },
): RosterPlayer => ({
  position: "QB",
  nflTeam: "KC",
  slot: "starter",
  slotIndex: 0,
  lineupPosition: "QB",
  projectedPoints: 22.5,
  injuryStatus: null,
  ...over,
});

const result = (over: Partial<BoardDataResult> = {}): BoardDataResult => ({
  season: 2026,
  week: 3,
  displayWeek: 3,
  isSeasonFallback: false,
  isOffRegularSeason: false,
  seasonId: 1,
  // No lineup unless a case is about one: every starter renders and no slot reads empty.
  rosterPositions: [],
  teams: [],
  isPending: false,
  isEmpty: false,
  errors: [],
  projectionsUpdatedAt: Date.now(),
  refetchAll: vi.fn(),
  ...over,
});

/** Proves the sort really landed in the URL, not just in the page's own state. */
function LocationProbe() {
  const location = useLocation();
  return (
    <div data-testid="location">{`${location.pathname}${location.search}`}</div>
  );
}

function renderPage(initialEntry = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // A fresh element every call, so `rerenderPage` really re-renders: React bails out of a
  // re-render handed the identical element it already holds.
  const ui = () => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <BoardPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(ui());
  return { ...view, rerenderPage: () => view.rerender(ui()) };
}

describe("BoardPage", () => {
  beforeEach(() => {
    realtime.isConnected = true;
    realtime.hasConnectedOnce = true;
    realtime.refreshNow = vi.fn();
    boardData.current = result();
  });

  it("shows skeletons while pending", () => {
    boardData.current = result({ isPending: true });
    const { container } = renderPage();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
  });

  it("shows the waiting card when there are no rows", () => {
    boardData.current = result({ isEmpty: true });
    renderPage();
    expect(screen.getByText("Waiting for the first sync")).toBeInTheDocument();
  });

  it("reaches the empty state when nfl_state never resolved a season", () => {
    boardData.current = result({
      season: null,
      week: null,
      displayWeek: null,
      seasonId: null,
      projectionsUpdatedAt: null,
      isEmpty: true,
    });
    renderPage();
    expect(screen.getByText("Waiting for the first sync")).toBeInTheDocument();
    expect(screen.getByText("Week —")).toBeInTheDocument();
  });

  it("names the failing section and keeps showing the rest of the board", () => {
    boardData.current = result({
      teams: [team({ teamId: 1 })],
      errors: [{ section: "Projections", message: "network down" }],
    });
    renderPage();
    expect(screen.getByText("Projections could not load")).toBeInTheDocument();
    expect(screen.getByText("owner1")).toBeInTheDocument();
  });

  it("renders teams in projection order inside a list", () => {
    boardData.current = result({
      teams: [
        team({ teamId: 1, projectedPoints: 90 }),
        team({ teamId: 2, projectedPoints: 140 }),
      ],
    });
    renderPage();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("owner2");
    expect(items[1]).toHaveTextContent("owner1");
  });

  it("groups eliminated teams under a divider", () => {
    boardData.current = result({
      teams: [
        team({ teamId: 1, projectedPoints: 10 }),
        team({
          teamId: 2,
          projectedPoints: 200,
          isEliminated: true,
          eliminatedWeek: 2,
        }),
      ],
    });
    renderPage();
    expect(screen.getByText("Eliminated (1)")).toBeInTheDocument();
  });

  it("names the provider exactly once, in the footer", () => {
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    renderPage();
    expect(screen.getByText("Projections: Sleeper")).toBeInTheDocument();
    expect(
      screen.queryByText(/Projections from Sleeper/),
    ).not.toBeInTheDocument();
  });

  it("leads the last-pull indicator with an absolute local time", () => {
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    renderPage();
    expect(screen.getByText(/^Updated /)).toBeInTheDocument();
  });

  it("shows the paused banner when realtime is down", () => {
    realtime.isConnected = false;
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    renderPage();
    expect(screen.getByText(PAUSED_BANNER_TEXT)).toBeInTheDocument();
  });

  it("says nothing about the socket on a cold load, and speaks only after a real drop", () => {
    // A cold load: the socket has never been up, so neither the banner nor the label is true.
    realtime.isConnected = false;
    realtime.hasConnectedOnce = false;
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    const { rerenderPage } = renderPage();
    expect(screen.queryByText(PAUSED_BANNER_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByText("reconnecting")).not.toBeInTheDocument();

    // The socket comes up: still nothing.
    realtime.isConnected = true;
    realtime.hasConnectedOnce = true;
    rerenderPage();
    expect(screen.queryByText(PAUSED_BANNER_TEXT)).not.toBeInTheDocument();
    expect(screen.queryByText("reconnecting")).not.toBeInTheDocument();

    // And now it drops — the one state both are about.
    realtime.isConnected = false;
    rerenderPage();
    expect(screen.getByText(PAUSED_BANNER_TEXT)).toBeInTheDocument();
    expect(screen.getByText("reconnecting")).toBeInTheDocument();
  });

  it("badges a pull older than the stale threshold", () => {
    boardData.current = result({
      teams: [team({ teamId: 1 })],
      projectionsUpdatedAt: Date.now() - STALE_AFTER_MS - MS_PER_MINUTE,
    });
    renderPage();
    expect(screen.getByText("Stale data")).toBeInTheDocument();
  });

  it("announces nothing on mount, even for a pull made an hour ago", () => {
    boardData.current = result({
      teams: [team({ teamId: 1 })],
      projectionsUpdatedAt: Date.now() - 60 * MS_PER_MINUTE,
    });
    const { container } = renderPage();
    const liveRegion = container.querySelector('[aria-live="polite"]');
    expect(liveRegion).not.toBeNull();
    expect(liveRegion).toBeEmptyDOMElement();
  });

  it("refreshes through the realtime hook, not a bare refetch", () => {
    realtime.isConnected = false;
    const refetchAll = vi.fn();
    boardData.current = result({ teams: [team({ teamId: 1 })], refetchAll });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Refresh now" }));
    expect(realtime.refreshNow).toHaveBeenCalledTimes(1);
    expect(refetchAll).not.toHaveBeenCalled();
  });

  it("filters teams as the search term settles", async () => {
    boardData.current = result({
      teams: [team({ teamId: 1 }), team({ teamId: 2, ownerName: "charlie" })],
    });
    renderPage();
    fireEvent.change(screen.getByLabelText(SEARCH_LABEL), {
      target: { value: "charlie" },
    });
    await waitFor(() => {
      expect(screen.queryByText("owner1")).not.toBeInTheDocument();
    });
    expect(screen.getByText("charlie")).toBeInTheDocument();
  });

  it("auto-expands the one team a player search matched and highlights the row", async () => {
    boardData.current = result({
      teams: [
        team({
          teamId: 1,
          roster: [player({ sleeperPlayerId: "p1", fullName: "Puka Nacua" })],
        }),
        team({
          teamId: 2,
          roster: [
            player({ sleeperPlayerId: "p2", fullName: "Bijan Robinson" }),
          ],
        }),
      ],
    });
    const { container } = renderPage();
    fireEvent.change(screen.getByLabelText(SEARCH_LABEL), {
      target: { value: "nacua" },
    });

    await waitFor(() => {
      expect(screen.getByText("Puka Nacua")).toBeInTheDocument();
    });
    expect(screen.queryByText("Bijan Robinson")).not.toBeInTheDocument();
    expect(screen.getByText("owner1")).toBeInTheDocument();
    expect(screen.queryByText("owner2")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-highlighted]")).toHaveLength(1);
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
  });

  it("lets a search-expanded card be closed and opened again", async () => {
    boardData.current = result({
      teams: [
        team({
          teamId: 1,
          roster: [player({ sleeperPlayerId: "p1", fullName: "Puka Nacua" })],
        }),
      ],
    });
    renderPage();
    fireEvent.change(screen.getByLabelText(SEARCH_LABEL), {
      target: { value: "nacua" },
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { expanded: true }),
      ).toBeInTheDocument();
    });

    // The tap the auto-expand used to swallow: an explicit close outranks it.
    fireEvent.click(screen.getByRole("button", { expanded: true }));
    expect(screen.getByRole("button", { expanded: false })).toBeInTheDocument();
    expect(screen.queryByText("Puka Nacua")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(screen.getByText("Puka Nacua")).toBeInTheDocument();
  });

  it("clears the search from the clear button, which appears only with a term", async () => {
    boardData.current = result({
      teams: [team({ teamId: 1 }), team({ teamId: 2, ownerName: "charlie" })],
    });
    renderPage();
    expect(
      screen.queryByRole("button", { name: "Clear search" }),
    ).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(SEARCH_LABEL), {
      target: { value: "charlie" },
    });
    await waitFor(() => {
      expect(screen.queryByText("owner1")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getByLabelText(SEARCH_LABEL)).toHaveValue("");
    await waitFor(() => {
      expect(screen.getByText("owner1")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "Clear search" }),
    ).not.toBeInTheDocument();
  });

  it("changes the sort and records it in the URL", async () => {
    boardData.current = result({
      teams: [
        team({ teamId: 1, projectedPoints: 200, faabRemaining: 1 }),
        team({ teamId: 2, projectedPoints: 10, faabRemaining: 99 }),
      ],
    });
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: "FAAB" }));
    await waitFor(() => {
      expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("owner2");
    });
    expect(screen.getByTestId("location")).toHaveTextContent("/?sort=faab");
  });

  it("says when the sort fell back because no projection is usable", () => {
    boardData.current = result({
      teams: [
        team({
          teamId: 1,
          projectedPoints: null,
          coveragePct: null,
          isProvisional: true,
        }),
      ],
    });
    renderPage();
    expect(
      screen.getByText(
        "No projections available, so teams are sorted by total points.",
      ),
    ).toBeInTheDocument();
  });

  it("labels the season when nfl_state has rolled past the last one played", () => {
    // The offseason shape. Unlabelled, last season's final table reads as this week's board.
    boardData.current = result({
      season: 2026,
      week: 17,
      displayWeek: 1,
      isSeasonFallback: true,
      isOffRegularSeason: true,
      teams: [team({ teamId: 1 })],
    });
    renderPage();
    expect(screen.getByText("Season 2026 (final)")).toBeInTheDocument();
    // The header names Sleeper's own week; the caveat names the week the numbers are from.
    expect(screen.getByRole("heading", { name: "Week 1" })).toBeInTheDocument();
    // Season-neutral: `season_type` leaves `regular` in the preseason too, so the sentence
    // says what is on screen rather than claiming the regular season is over.
    expect(
      screen.getByText("Showing week 17, the last week with final results."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Regular season complete/)).toBeNull();
  });

  it("says nothing about the season or the scope during the regular season", () => {
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    renderPage();
    expect(screen.getByRole("heading", { name: "Week 3" })).toBeInTheDocument();
    expect(screen.queryByText(/\(final\)/)).toBeNull();
    expect(screen.queryByText(/last week with final results/)).toBeNull();
  });
});

/**
 * Ben's addendum 2: "make it possible so I can filter and see every team's TE or all their RBs
 * in a quick view — my TE just got injured and I need to figure out who would bid on his
 * replacement."
 */
describe("BoardPage position quick view", () => {
  const LEAGUE_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"];

  const positionBoard = () =>
    result({
      rosterPositions: LEAGUE_SLOTS,
      teams: [
        team({
          teamId: 1,
          faabRemaining: 715,
          roster: [
            player({
              sleeperPlayerId: "kelce",
              fullName: "Travis Kelce",
              position: "TE",
              slotIndex: 5,
              lineupPosition: "TE",
              projectedPoints: 14.1,
            }),
          ],
        }),
        team({ teamId: 2, faabRemaining: 40, roster: [] }),
      ],
    });

  beforeEach(() => {
    boardData.current = positionBoard();
  });

  it("renders the position view for ?pos=TE, not the team grid", () => {
    renderPage("/?pos=TE");
    expect(screen.getByText("FAAB 715")).toBeInTheDocument();
    expect(screen.getByText("Travis Kelce")).toBeInTheDocument();
    // The team card's own projection line is not on screen: this is the other view.
    expect(screen.getByText("no TE")).toBeInTheDocument();
    expect(screen.queryByText("proj")).toBeNull();
  });

  it("reads a lower-case parameter as the same position", () => {
    renderPage("/?pos=te");
    expect(screen.getByText("FAAB 715")).toBeInTheDocument();
  });

  it("round-trips the segmented control through the URL", async () => {
    renderPage();
    expect(screen.queryByText("FAAB 715")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "TE" }));
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/?pos=TE");
    });
    expect(screen.getByText("FAAB 715")).toBeInTheDocument();

    // Back to All: the parameter goes away rather than becoming `?pos=all`.
    fireEvent.click(screen.getByRole("radio", { name: "All positions" }));
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/");
    });
    expect(screen.getByTestId("location")).not.toHaveTextContent("pos=");
    expect(screen.queryByText("FAAB 715")).toBeNull();
  });

  it("offers FAAB and projection only while a position is selected", () => {
    renderPage("/?pos=TE");
    expect(screen.getByRole("radio", { name: "FAAB" })).toBeInTheDocument();
    expect(
      screen.getByRole("radio", { name: "Projection" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Total" })).toBeNull();
  });

  it("defaults the position view to FAAB and re-sorts on the projection toggle", async () => {
    boardData.current = result({
      rosterPositions: LEAGUE_SLOTS,
      teams: [
        team({ teamId: 1, faabRemaining: 10, projectedPoints: 200 }),
        team({ teamId: 2, faabRemaining: 90, projectedPoints: 10 }),
      ],
    });
    renderPage("/?pos=TE");
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("owner2");

    fireEvent.click(screen.getByRole("radio", { name: "Projection" }));
    await waitFor(() => {
      expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("owner1");
    });
    expect(screen.getByTestId("location")).toHaveTextContent("pos=TE");
    expect(screen.getByTestId("location")).toHaveTextContent("sort=projection");
  });

  it("keeps the search working inside the position view", async () => {
    renderPage("/?pos=TE");
    fireEvent.change(screen.getByLabelText(SEARCH_LABEL), {
      target: { value: "kelce" },
    });
    await waitFor(() => {
      expect(screen.queryByText("owner2")).not.toBeInTheDocument();
    });
    expect(screen.getByText("owner1")).toBeInTheDocument();
    // A player search auto-expands the row it matched here too, so the name appears both
    // inline on the row and in the roster panel below it.
    expect(screen.getAllByText("Travis Kelce").length).toBeGreaterThan(1);
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
  });

  it("says nothing about a sort fallback in the position view", () => {
    boardData.current = result({
      rosterPositions: LEAGUE_SLOTS,
      teams: [
        team({
          teamId: 1,
          projectedPoints: null,
          coveragePct: null,
          isProvisional: true,
        }),
      ],
    });
    renderPage("/?pos=TE");
    expect(
      screen.queryByText(
        "No projections available, so teams are sorted by total points.",
      ),
    ).toBeNull();
  });
});
