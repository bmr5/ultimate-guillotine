import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";

const state = vi.hoisted(() => ({ seasons: [] as unknown[] }));

vi.mock("@/history/useSeasonResults", () => ({
  useSeasonResults: () => ({
    seasons: state.seasons,
    loadedAt: Date.parse("2026-09-09T12:00:00Z"),
    labelForMember: () => "Bravo",
    isPending: false,
    errors: [],
  }),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HistoryPage", () => {
  it("shows the empty state when nothing is loaded", () => {
    state.seasons = [];
    renderPage();
    expect(screen.getByText("No seasons loaded yet.")).toBeInTheDocument();
  });

  it("lists the winners strip and one card per season, newest first", () => {
    state.seasons = [
      {
        season: 2024,
        championLabel: "Alpha",
        coChampionLabel: null,
        runnerUpLabel: null,
        thirdLabel: null,
        teamCount: 19,
        eliminations: [],
        notes: null,
        loadedAt: "2026-09-09T12:00:00Z",
      },
      {
        season: 2023,
        championLabel: "Bravo",
        coChampionLabel: null,
        runnerUpLabel: null,
        thirdLabel: null,
        teamCount: 20,
        eliminations: [],
        notes: null,
        loadedAt: "2026-09-09T12:00:00Z",
      },
    ];
    renderPage();
    const headings = screen.getAllByText(/Champion 20\d\d/);
    expect(headings.map((node) => node.textContent)).toEqual([
      "Champion 2024",
      "Champion 2023",
    ]);
    expect(screen.getByRole("list", { name: /winners/i })).toBeInTheDocument();
  });
});
