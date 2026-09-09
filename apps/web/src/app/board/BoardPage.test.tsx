import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BoardTeam } from "@/board/types";
import type { BoardDataResult } from "@/board/useBoardData";

const boardData = vi.hoisted(() => ({ current: null as BoardDataResult | null }));
const realtime = vi.hoisted(() => ({
  isConnected: true,
  refreshNow: vi.fn(),
}));

vi.mock("@/board/useBoardData", () => ({
  useBoardData: () => boardData.current,
}));

vi.mock("@/board/useLeagueBoardRealtime", () => ({
  useLeagueBoardRealtime: () => ({
    isConnected: realtime.isConnected,
    reconnectAttempts: 0,
    refreshNow: realtime.refreshNow,
  }),
}));

import { BoardPage } from "./BoardPage";

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
  wins: 1,
  losses: 0,
  ties: 0,
  pointsFor: 100,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  roster: [],
  ...over,
});

const result = (over: Partial<BoardDataResult> = {}): BoardDataResult => ({
  season: 2026,
  week: 3,
  seasonId: 1,
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <BoardPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BoardPage", () => {
  beforeEach(() => {
    realtime.isConnected = true;
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
    expect(
      screen.getByText("Live updates are paused. Polling every 60 seconds."),
    ).toBeInTheDocument();
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
    fireEvent.change(screen.getByLabelText("Search owner, team, or player"), {
      target: { value: "charlie" },
    });
    await waitFor(() => {
      expect(screen.queryByText("owner1")).not.toBeInTheDocument();
    });
    expect(screen.getByText("charlie")).toBeInTheDocument();
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
        "No projections available, so teams are sorted by points for.",
      ),
    ).toBeInTheDocument();
  });
});
