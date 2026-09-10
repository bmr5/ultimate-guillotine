import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BOARD_LOADING_LABEL } from "@/board/components/BoardStates";
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

const playerCard = vi.hoisted(() => ({
  current: {
    transactions: [],
    moves: [],
    seasonScores: [],
    directory: null as {
      sleeper_player_id: string;
      full_name: string;
      position: string | null;
      team: string | null;
      injury_status: string | null;
    } | null,
    otherPlayers: [],
    registered: [],
    isPending: false,
    errors: [],
    refetch: vi.fn(),
  },
}));

vi.mock("@/player/usePlayerCard", () => ({
  usePlayerCard: () => playerCard.current,
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
  risk: null,
  teamName: `Team ${over.teamId}`,
  ownerName: `owner${over.teamId}`,
  sleeperRosterId: over.teamId,
  score: null,
  scoreSyncedAt: null,
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
  livePoints: null,
  draft: null,
  draftedHere: false,
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
  draftPicks: [],
  memberIdByTeamId: new Map(),
  teams: [],
  isPending: false,
  isEmpty: false,
  errors: [],
  projectionsUpdatedAt: Date.now(),
  scoresUpdatedAt: null,
  oddsUpdatedAt: null,
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

  it("shows skeletons while pending, and says what is loading", () => {
    boardData.current = result({ isPending: true });
    const { container } = renderPage();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0,
    );
    expect(
      screen.getByRole("status", { name: BOARD_LOADING_LABEL }),
    ).toBeInTheDocument();
  });

  it("keeps cut watch on the full pool when the board is searched", async () => {
    boardData.current = result({
      week: 1,
      teams: [
        team({ teamId: 1, projectedPoints: 80 }),
        team({ teamId: 2, projectedPoints: 90 }),
        team({ teamId: 3, projectedPoints: 100 }),
      ],
    });
    renderPage();
    const watch = within(screen.getByRole("region", { name: "Cut watch" }));
    expect(watch.getByText("owner1")).toBeInTheDocument();
    expect(watch.getByText("owner2")).toBeInTheDocument();
    expect(watch.getByText("VS")).toBeInTheDocument();
    expect(watch.getAllByText("Actual")).toHaveLength(2);
    expect(watch.getAllByText("Projected")).toHaveLength(2);
    fireEvent.change(screen.getByRole("searchbox", { name: SEARCH_LABEL }), {
      target: { value: "owner3" },
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /owner1/ }),
      ).not.toBeInTheDocument(),
    );
    expect(watch.getByText("owner1")).toBeInTheDocument();
    expect(watch.getByText("owner2")).toBeInTheDocument();
  });

  it("expands the matchup to show the safety gap and lineups", () => {
    boardData.current = result({
      week: 1,
      teams: [
        team({ teamId: 1, projectedPoints: 80 }),
        team({ teamId: 2, projectedPoints: 90 }),
        team({ teamId: 3, projectedPoints: 100 }),
      ],
    });
    renderPage();
    const watch = within(screen.getByRole("region", { name: "Cut watch" }));
    const toggle = watch.getByRole("button", { name: "Show matchup details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(watch.queryByText(/pts to the safety line/)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      watch.getByText("20.00 pts to the safety line", { exact: false }),
    ).toBeVisible();
    expect(
      watch.getByRole("heading", { name: "owner1 · Starters" }),
    ).toBeVisible();
    expect(
      watch.getByRole("heading", { name: "owner2 · Starters" }),
    ).toBeVisible();
    fireEvent.click(toggle);
    expect(
      watch.queryByRole("heading", { name: "owner1 · Starters" }),
    ).not.toBeInTheDocument();
  });

  it("keeps a broad tie to two names and puts the other contenders in details", () => {
    boardData.current = result({
      week: 1,
      teams: Array.from({ length: 6 }, (_, index) =>
        team({
          teamId: index + 1,
          projectedPoints: 80 + index,
          score: index === 5 ? 10 : 0,
        }),
      ),
    });
    renderPage();
    const watch = within(screen.getByRole("region", { name: "Cut watch" }));
    expect(watch.getByText("owner1")).toBeVisible();
    expect(watch.getByText("owner2")).toBeVisible();
    expect(watch.queryByText(/owner3/)).not.toBeInTheDocument();
    expect(watch.getByText(/Cutoff tied\. Projections/)).toBeVisible();
    fireEvent.click(
      watch.getByRole("button", { name: "Show matchup details" }),
    );
    expect(
      watch.getByText(
        /Teams at or below the cutoff: owner1, owner2, owner3, owner4, owner5/,
      ),
    ).toBeVisible();
  });

  it("updates cut watch from projected to current bottom two when scores arrive", () => {
    const teams = [
      team({ teamId: 1, projectedPoints: 80 }),
      team({ teamId: 2, projectedPoints: 90 }),
      team({ teamId: 3, projectedPoints: 100 }),
    ];
    boardData.current = result({ week: 1, teams });
    const { rerenderPage } = renderPage();
    boardData.current = result({
      week: 1,
      teams: teams.map((team, index) => ({
        ...team,
        score: [40, 10, 20][index],
      })),
    });
    rerenderPage();
    const watch = within(screen.getByRole("region", { name: "Cut watch" }));
    expect(watch.getByText(/Current bottom two/)).toBeInTheDocument();
    expect(watch.queryByText("owner1")).not.toBeInTheDocument();
    expect(watch.getByText("owner2")).toBeInTheDocument();
    expect(watch.getByText("owner3")).toBeInTheDocument();
  });

  it("does not advertise a new gulag after Week 11 or outside the current season", () => {
    boardData.current = result({ week: 12, teams: [team({ teamId: 1 })] });
    const { rerenderPage } = renderPage();
    expect(
      screen.queryByRole("region", { name: "Cut watch" }),
    ).not.toBeInTheDocument();
    boardData.current = result({
      week: 1,
      isOffRegularSeason: true,
      teams: [team({ teamId: 1 })],
    });
    rerenderPage();
    expect(
      screen.queryByRole("region", { name: "Cut watch" }),
    ).not.toBeInTheDocument();
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

  /**
   * Ben, 2026-09-10: "make the board always one column. I find it confusing to have 2 cols on a
   * 1-18 ranked board." A rank only reads down a single column, so no breakpoint may put one
   * back — not on the live list, not on the eliminated list below the divider, and not on the
   * skeleton that stands in for both before the first payload lands.
   */
  describe("the board's single column", () => {
    const gridLists = (container: HTMLElement) =>
      [...container.querySelectorAll("ul")].filter((list) =>
        list.className.includes("grid-cols-1"),
      );

    const expectOneColumn = (container: HTMLElement) => {
      const lists = gridLists(container);
      expect(lists.length).toBeGreaterThan(0);
      for (const list of lists) {
        expect(list.className).not.toMatch(/\b(?:sm|md|lg|xl|2xl):grid-cols-/);
      }
    };

    it("holds one column on the live list at every breakpoint", () => {
      boardData.current = result({
        teams: [
          team({ teamId: 1, projectedPoints: 140 }),
          team({
            teamId: 2,
            projectedPoints: 90,
            isEliminated: true,
            eliminatedWeek: 2,
          }),
        ],
      });
      const { container } = renderPage();
      // Both lists: the active board and the eliminated group under the divider.
      expect(gridLists(container)).toHaveLength(2);
      expectOneColumn(container);
    });

    it("holds one column on the skeleton, so the two never disagree", () => {
      boardData.current = result({ isPending: true });
      const { container } = renderPage();
      expectOneColumn(container);
    });
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

  /**
   * Ben: "why does it show that it updated at 9:30PM it should always be realtime!" The stamp
   * was `team_week_projections.computed_at`, which only moves when a projection is recomputed.
   * Once the week has a score row, the header leads with the score sync's own `synced_at` and
   * keeps the projections time as a smaller second line, because the two figures on every card
   * are pulled on different clocks and one stamp cannot truthfully describe both.
   */
  describe("the last-pull stamps", () => {
    const stamp = (container: HTMLElement) =>
      container.querySelector("[data-stamp]");

    it("leads with the scores once the week has a score row", () => {
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        scoresUpdatedAt: Date.now(),
      });
      const { container } = renderPage();
      expect(stamp(container)).toHaveAttribute("data-stamp", "scores");
      expect(screen.getByText(/^Scores updated /)).toBeInTheDocument();
    });

    it("keeps the projections time as a smaller second line", () => {
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        scoresUpdatedAt: Date.now(),
        projectionsUpdatedAt: Date.now() - 20 * MS_PER_MINUTE,
      });
      const { container } = renderPage();
      const second = container.querySelector("[data-projection-stamp]");
      expect(second).not.toBeNull();
      expect(second).toHaveTextContent(/^Projections pulled /);
      // Hidden from assistive tech like the two stamps above it: the live region is the one
      // thing that should speak about freshness, and it speaks on minute boundaries.
      expect(second).toHaveAttribute("aria-hidden", "true");
    });

    it("falls back to the one plain stamp before the first score sync", () => {
      // No score row yet, so the line above is already the projections stamp and repeating it
      // underneath would say the same thing twice.
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        scoresUpdatedAt: null,
      });
      const { container } = renderPage();
      expect(stamp(container)).toHaveAttribute("data-stamp", "projections");
      expect(screen.getByText(/^Updated /)).toBeInTheDocument();
      expect(container.querySelector("[data-projection-stamp]")).toBeNull();
    });

    it("says when the Daily computed the odds, under the other stamps", () => {
      // Ben: "just write the last time it was run so people know". The Daily's own
      // `snapshot_at`, on its own line, hidden from assistive tech like the stamps above it.
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        oddsUpdatedAt: Date.now(),
      });
      const { container } = renderPage();
      const odds = container.querySelector("[data-odds-stamp]");
      expect(odds).toHaveTextContent(/^Odds as of /);
      expect(odds).toHaveAttribute("aria-hidden", "true");
    });

    it("drops the odds line before the week's first Daily", () => {
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        oddsUpdatedAt: null,
      });
      const { container } = renderPage();
      expect(container.querySelector("[data-odds-stamp]")).toBeNull();
    });

    it("does not call the board stale over old odds", () => {
      // The odds are computed twice a day at most; their age says nothing about the scores.
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        scoresUpdatedAt: Date.now(),
        oddsUpdatedAt: Date.now() - STALE_AFTER_MS - MS_PER_MINUTE,
      });
      renderPage();
      expect(screen.queryByText("Stale data")).not.toBeInTheDocument();
    });

    it("measures staleness against the scores once they lead", () => {
      // The scores are the newer of the two by construction, so an hours-old `computed_at`
      // beside a score pulled a minute ago is not a stale board.
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        scoresUpdatedAt: Date.now(),
        projectionsUpdatedAt: Date.now() - STALE_AFTER_MS - MS_PER_MINUTE,
      });
      renderPage();
      expect(screen.queryByText("Stale data")).not.toBeInTheDocument();
    });

    it("still badges a board whose scores themselves have gone stale", () => {
      boardData.current = result({
        teams: [team({ teamId: 1 })],
        scoresUpdatedAt: Date.now() - STALE_AFTER_MS - MS_PER_MINUTE,
      });
      renderPage();
      expect(screen.getByText("Stale data")).toBeInTheDocument();
    });
  });

  /**
   * The emphasis is a board-wide decision, made once and handed to every card, so the two
   * figure columns line up down the grid.
   */
  describe("score emphasis", () => {
    const emphasized = (container: HTMLElement) =>
      [...container.querySelectorAll("[data-figure][data-emphasized]")].map(
        (node) => node.getAttribute("data-figure"),
      );

    it("emphasises the projection while every team is scoreless", () => {
      boardData.current = result({
        teams: [team({ teamId: 1, score: 0 }), team({ teamId: 2, score: 0 })],
      });
      const { container } = renderPage();
      expect(emphasized(container)).toEqual(["projection", "projection"]);
    });

    it("emphasises the score on every card once any team has scored", () => {
      boardData.current = result({
        teams: [
          team({ teamId: 1, score: 0 }),
          team({ teamId: 2, score: 88.1 }),
        ],
      });
      const { container } = renderPage();
      expect(emphasized(container)).toEqual(["score", "score"]);
    });

    it("does not flip the emphasis because a search narrowed the board", async () => {
      // The question is what the week is doing, not what is currently on screen: narrowing to
      // the one scoreless team must not put every visible card back on projection emphasis.
      boardData.current = result({
        teams: [
          team({ teamId: 1, score: 0, ownerName: "quiet" }),
          team({ teamId: 2, score: 88.1, ownerName: "loud" }),
        ],
      });
      const { container } = renderPage();
      fireEvent.change(screen.getByLabelText(SEARCH_LABEL), {
        target: { value: "quiet" },
      });
      // The search box is debounced, so the narrowing lands a tick later than the keystroke.
      await waitFor(() => {
        expect(screen.queryByText("loud")).not.toBeInTheDocument();
      });
      expect(emphasized(container)).toEqual(["score"]);
    });
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
    expect(screen.getByText("$715")).toBeInTheDocument();
    expect(screen.getByText("Travis Kelce")).toBeInTheDocument();
    // The team card's own projection line is not on screen: this is the other view.
    expect(screen.getByText("no TE")).toBeInTheDocument();
    expect(screen.queryByText("proj")).toBeNull();
  });

  it("reads a lower-case parameter as the same position", () => {
    renderPage("/?pos=te");
    expect(screen.getByText("no TE")).toBeInTheDocument();
  });

  it("round-trips the segmented control through the URL", async () => {
    renderPage();
    // `no TE` is the position view's own line: the team card's FAAB figure reads `$715` as
    // well, so the figure no longer says which view is on screen.
    expect(screen.queryByText("no TE")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: "TE" }));
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/?pos=TE");
    });
    expect(screen.getByText("no TE")).toBeInTheDocument();

    // Back to All: the parameter goes away rather than becoming `?pos=all`.
    fireEvent.click(screen.getByRole("radio", { name: "All positions" }));
    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent("/");
    });
    expect(screen.getByTestId("location")).not.toHaveTextContent("pos=");
    expect(screen.queryByText("no TE")).toBeNull();
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

describe("BoardPage FAAB tiers", () => {
  it("renders the three tier cards for ?view=tiers and no team grid", async () => {
    renderPage("/?view=tiers");
    const tiers = await screen.findByRole("list", { name: /FAAB tiers/i });
    const cards = within(tiers)
      .getAllByRole("listitem")
      .filter((li) => li.hasAttribute("data-tier"));
    expect(cards.map((li) => li.getAttribute("data-tier"))).toEqual([
      "rich",
      "medium",
      "poor",
    ]);
    expect(screen.queryByText(/Total/)).toBeNull();
    expect(screen.getByRole("radio", { name: /FAAB tiers/i })).toHaveAttribute(
      "data-state",
      "on",
    );
  });
});

describe("BoardPage leaving the FAAB tiers", () => {
  it("returns to the board when a position or All is chosen", async () => {
    renderPage("/?view=tiers");
    await screen.findByRole("list", { name: /FAAB tiers/i });
    fireEvent.click(screen.getByRole("radio", { name: "TE" }));
    await waitFor(() =>
      expect(screen.queryByRole("list", { name: /FAAB tiers/i })).toBeNull(),
    );
    expect(screen.getByRole("radio", { name: "TE" })).toHaveAttribute(
      "data-state",
      "on",
    );
    fireEvent.click(screen.getByRole("radio", { name: /All positions/i }));
    await waitFor(() =>
      expect(
        screen.getByRole("radio", { name: /All positions/i }),
      ).toHaveAttribute("data-state", "on"),
    );
    expect(screen.queryByRole("list", { name: /FAAB tiers/i })).toBeNull();
  });
});

describe("the player card", () => {
  const nacua = player({ sleeperPlayerId: "9493", fullName: "Puka Nacua" });

  beforeEach(() => {
    playerCard.current = { ...playerCard.current, directory: null };
  });

  it("opens from the URL on load, labelled by the player's name", () => {
    boardData.current = result({
      teams: [team({ teamId: 1, roster: [nacua] })],
    });
    renderPage("/?player=9493");
    expect(
      screen.getByRole("dialog", { name: "Puka Nacua" }),
    ).toBeInTheDocument();
  });

  it("opens when a name is tapped, and writes the player into the URL", () => {
    boardData.current = result({
      teams: [team({ teamId: 1, roster: [nacua] })],
    });
    renderPage("/?sort=faab");
    fireEvent.click(screen.getByRole("button", { name: /owner1/ }));
    fireEvent.click(screen.getByRole("button", { name: "Puka Nacua" }));
    expect(
      screen.getByRole("dialog", { name: "Puka Nacua" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/?sort=faab&player=9493",
    );
  });

  it("closes by taking the player out of the URL, keeping the rest", () => {
    boardData.current = result({
      teams: [team({ teamId: 1, roster: [nacua] })],
    });
    renderPage("/?sort=faab&player=9493");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/?sort=faab");
  });

  it("still opens for a player the board does not hold", () => {
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    playerCard.current = {
      ...playerCard.current,
      directory: {
        sleeper_player_id: "9493",
        full_name: "Puka Nacua",
        position: "WR",
        team: "LAR",
        injury_status: null,
      },
    };
    renderPage("/?player=9493");
    expect(
      screen.getByRole("dialog", { name: "Puka Nacua" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Not rostered this week")).toBeInTheDocument();
  });
});
