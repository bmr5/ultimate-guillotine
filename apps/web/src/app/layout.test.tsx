import { lazy } from "react";
import { act, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import App, { PAGE_FALLBACK_LABEL } from "./layout";

/**
 * The shell renders every page inside one Suspense boundary, so a page that arrives in its own
 * chunk shows the placeholder rather than a blank outlet while the chunk is on its way.
 */
describe("App layout", () => {
  it("shows the page placeholder until a lazy page resolves, then the page", async () => {
    let resolvePage: () => void = () => undefined;
    const LazyPage = lazy(
      () =>
        new Promise<{ default: () => React.JSX.Element }>((resolve) => {
          resolvePage = () =>
            resolve({ default: () => <p>the trades page</p> });
        }),
    );
    const router = createMemoryRouter(
      [
        {
          path: "/",
          Component: App,
          children: [{ path: "trades", element: <LazyPage /> }],
        },
      ],
      { initialEntries: ["/trades"] },
    );
    render(<RouterProvider router={router} />);

    expect(
      screen.getByRole("status", { name: PAGE_FALLBACK_LABEL }),
    ).toBeInTheDocument();
    expect(screen.queryByText("the trades page")).toBeNull();

    await act(async () => {
      resolvePage();
      await Promise.resolve();
    });
    expect(await screen.findByText("the trades page")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: PAGE_FALLBACK_LABEL }),
    ).toBeNull();
  });

  it("keeps the three page links, with the current one marked", () => {
    const router = createMemoryRouter(
      [
        {
          path: "/",
          Component: App,
          children: [{ path: "history", element: <p>history</p> }],
        },
      ],
      { initialEntries: ["/history"] },
    );
    render(<RouterProvider router={router} />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Board",
      "Trades",
      "History",
    ]);
    expect(screen.getByRole("link", { name: "History" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
