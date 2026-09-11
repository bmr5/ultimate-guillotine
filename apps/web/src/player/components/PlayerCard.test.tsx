import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Dialog } from "@/components/ui/dialog";

import type { PlayerCardView } from "../derive/card";
import {
  NOT_ROSTERED_LABEL,
  PLAYER_LOADING_LABEL,
  PlayerCardContent,
  UNDRAFTED_LABEL,
} from "./PlayerCard";

const view = (over: Partial<PlayerCardView> = {}): PlayerCardView => ({
  name: "Puka Nacua",
  position: "WR",
  nflTeam: "LAR",
  injuryStatus: null,
  numbers: {
    rostered: true,
    projected: 14.1,
    live: 7.8,
    season: { total: 19.9, weeks: 3 },
  },
  draft: {
    amount: 53,
    pickNo: 1,
    ownerName: "Ray Regime",
    contextLine: "9th priciest pick · 4th WR · WR average $22",
    stillHere: true,
  },
  journey: [
    {
      kind: "drafted",
      key: "draft",
      at: "2026-09-07T23:01:30Z",
      week: null,
      teamId: 11,
      amount: 53,
      pickNo: 1,
    },
    {
      kind: "traded",
      key: "tx:5",
      at: "2026-09-08T14:01:40Z",
      week: 1,
      fromTeamId: 11,
      toTeamId: 16,
      others: [{ sleeperPlayerId: "12534", fromTeamId: 16, toTeamId: 11 }],
      faab: [{ amount: 65, fromTeamId: 11, toTeamId: 16 }],
      registered: {
        key: "r1",
        tradeCode: "T-2026-003",
        announcement: "Puka for Bowers plus 65",
        rescinded: false,
      },
    },
    {
      kind: "claimed",
      key: "tx:9",
      at: "2026-09-23T00:00:00Z",
      week: 3,
      teamId: 3,
      bid: 12,
    },
  ],
  ownerLabelByTeamId: new Map([
    [11, "Ray Regime"],
    [16, "Rick Vice"],
    [3, "chobes"],
  ]),
  playerNameById: new Map([["12534", "Brock Bowers"]]),
  ...over,
});

const renderContent = (
  over: Partial<PlayerCardView> = {},
  state: {
    isPending?: boolean;
    errors?: { section: string; message: string }[];
  } = {},
) =>
  render(
    <Dialog open>
      <PlayerCardContent
        view={view(over)}
        isPending={state.isPending ?? false}
        errors={state.errors ?? []}
        onRetry={vi.fn()}
      />
    </Dialog>,
  );

describe("PlayerCardContent", () => {
  it("leads with the name and the position line", () => {
    renderContent();
    expect(
      screen.getByRole("heading", { name: "Puka Nacua" }),
    ).toBeInTheDocument();
    expect(screen.getByText("WR · LAR")).toBeInTheDocument();
  });

  it("shows the numbers with the rostered-weeks caption", () => {
    renderContent();
    expect(screen.getByText("14.1")).toBeInTheDocument();
    expect(screen.getByText("7.8")).toBeInTheDocument();
    expect(screen.getByText("19.9")).toBeInTheDocument();
    expect(screen.getByText("in 3 rostered weeks")).toBeInTheDocument();
  });

  it("shows the draft, the drafter, and the context line", () => {
    renderContent();
    expect(
      screen.getByText("$53 draft ($265 FAAB at 5:1) · pick 1 · Ray Regime"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("9th priciest pick · 4th WR · WR average $22"),
    ).toBeInTheDocument();
  });

  it("reads Undrafted with no context line for an undrafted pickup", () => {
    renderContent({ draft: null });
    expect(screen.getByText(UNDRAFTED_LABEL)).toBeInTheDocument();
    expect(screen.queryByText(/priciest/)).not.toBeInTheDocument();
  });

  it("says the player is not rostered this week when no team holds him", () => {
    renderContent({
      numbers: { rostered: false, season: { total: 0, weeks: 0 } },
    });
    expect(screen.getByText(NOT_ROSTERED_LABEL)).toBeInTheDocument();
  });

  it("tells the journey oldest first, naming owners, the other players, the FAAB and the announcement", () => {
    renderContent();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent(
      "Drafted by Ray Regime for $53 draft ($265 FAAB at 5:1)",
    );
    expect(items[1]).toHaveTextContent("Traded from Ray Regime to Rick Vice");
    expect(items[1]).toHaveTextContent("Brock Bowers to Ray Regime");
    expect(items[1]).toHaveTextContent("$65 FAAB from Ray Regime to Rick Vice");
    expect(items[1]).toHaveTextContent("T-2026-003");
    expect(items[1]).toHaveTextContent("Puka for Bowers plus 65");
    expect(items[items.length - 1]).toHaveTextContent(
      "Claimed by chobes for a $12 bid",
    );
  });

  it("shows the loading sentence while the reads are on their way", () => {
    renderContent({}, { isPending: true });
    expect(
      screen.getByRole("status", { name: PLAYER_LOADING_LABEL }),
    ).toBeInTheDocument();
  });

  it("names a failed section with a retry, and keeps the rest", () => {
    renderContent(
      {},
      { errors: [{ section: "Transactions", message: "network down" }] },
    );
    expect(screen.getByText("Transactions could not load")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Puka Nacua" }),
    ).toBeInTheDocument();
  });

  it("strikes through a rescinded announcement", () => {
    renderContent({
      journey: [
        {
          kind: "announced",
          key: "reg:r2",
          at: "2026-09-10T00:00:00Z",
          week: 1,
          registered: {
            key: "r2",
            tradeCode: "T-2026-004",
            announcement: "Undo that",
            rescinded: true,
          },
        },
      ],
    });
    expect(screen.getByRole("listitem")).toHaveAttribute(
      "data-rescinded",
      "true",
    );
    fireEvent.click(screen.getByText("T-2026-004"));
  });
});
