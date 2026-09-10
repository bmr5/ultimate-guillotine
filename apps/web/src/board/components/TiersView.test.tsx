import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { faabTiers } from "../derive/tiers";
import type { BoardTeam } from "../types";
import { TiersView } from "./TiersView";

const team = (
  teamId: number,
  ownerName: string,
  faabRemaining: number,
): BoardTeam =>
  ({
    teamId,
    ownerName,
    teamName: `Team ${teamId}`,
    faabRemaining,
  }) as BoardTeam;

describe("TiersView", () => {
  it("shows every team's FAAB in its tier card and draws a dot per team", () => {
    const tiers = faabTiers([
      team(1, "Whale", 900),
      team(2, "Middle", 400),
      team(3, "Broke", 10),
    ]);
    const { container } = render(<TiersView tiers={tiers} />);
    const rich = screen
      .getByRole("list", { name: /FAAB tiers/i })
      .querySelector('[data-tier="rich"]');
    expect(rich).not.toBeNull();
    expect(within(rich as HTMLElement).getByText("Whale")).toBeInTheDocument();
    expect(within(rich as HTMLElement).getByText("$900")).toBeInTheDocument();
    expect(container.querySelectorAll("circle[data-team]")).toHaveLength(3);
    expect(
      within(rich as HTMLElement).getByText("richest"),
    ).toBeInTheDocument();
    expect(
      within(rich as HTMLElement).getByText(/Whale alone at the top/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /bell curve/i }),
    ).toBeInTheDocument();
  });

  it("rules the axis to the next $100 in $50 bands and reads out a band's teams on hover", () => {
    const tiers = faabTiers([
      team(1, "Whale", 710),
      team(2, "Middle", 400),
      team(3, "Broke", 40),
    ]);
    const { container } = render(<TiersView tiers={tiers} />);
    expect(container.querySelectorAll("rect[data-band]")).toHaveLength(16);
    expect(screen.getByText("$800")).toBeInTheDocument();
    fireEvent.pointerEnter(
      screen.getByRole("button", { name: /^\$700–\$750: 1 team$/ }),
    );
    const readout = container.querySelector("[data-readout]") as HTMLElement;
    expect(within(readout).getByText("Whale")).toBeInTheDocument();
    expect(within(readout).queryByText("Middle")).toBeNull();
    fireEvent.pointerEnter(
      screen.getByRole("button", { name: /^\$100–\$150: 0 teams$/ }),
    );
    expect(
      within(readout).getByText("Nobody in this band."),
    ).toBeInTheDocument();
  });
});
