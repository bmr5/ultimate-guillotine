import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LoadingState } from "./loading-state";

describe("LoadingState", () => {
  it("is a status region named by its label, so a screen reader hears what is loading", () => {
    render(<LoadingState label="Loading trades" />);
    expect(
      screen.getByRole("status", { name: "Loading trades" }),
    ).toBeInTheDocument();
  });

  it("shows the label with a trailing ellipsis and a spinner that is decoration only", () => {
    const { container } = render(<LoadingState label="Loading trades" />);
    expect(screen.getByText("Loading trades…")).toBeInTheDocument();
    const spinner = container.querySelector("svg");
    expect(spinner).not.toBeNull();
    expect(spinner).toHaveAttribute("aria-hidden", "true");
  });
});
