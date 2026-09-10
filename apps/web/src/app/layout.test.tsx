import { lazy } from "react";
import { act, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BOARD_LOADING_LABEL } from "@/board/components/BoardStates";
import { SEASONS_LOADING_LABEL } from "@/history/components/HistorySkeleton";
import { TRADES_LOADING_LABEL } from "@/history/components/TradesSkeleton";
import { MUTE_LABEL } from "@/music/MusicToggle";

import App from "./layout";

/**
 * The chunks are never fetched here: `prefetchPages` is what the shell calls, and the test only
 * needs to see that it was called, not what it loads.
 */
const prefetchPages = vi.hoisted(() => vi.fn());
vi.mock("@/app/lazyPages", () => ({ prefetchPages }));

/** A page whose chunk never arrives, so the shell's loading state can be observed at leisure. */
function neverResolving() {
  return lazy(
    () => new Promise<{ default: () => React.JSX.Element }>(() => {}),
  );
}

function makeRouter(
  initialEntry: string,
  children: Parameters<typeof createMemoryRouter>[0][number]["children"],
) {
  return createMemoryRouter([{ path: "/", Component: App, children }], {
    initialEntries: [initialEntry],
  });
}

/**
 * The shell renders every page inside one Suspense boundary, so a page that arrives in its own
 * chunk shows a loading state rather than a blank outlet while the chunk is on its way — and
 * the loading state is the destination's own, named for what it is loading.
 */
describe("App layout", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    prefetchPages.mockClear();
  });

  it("shows the trades loading state on a cold load of /trades until the page resolves", async () => {
    let resolvePage: () => void = () => undefined;
    const LazyPage = lazy(
      () =>
        new Promise<{ default: () => React.JSX.Element }>((resolve) => {
          resolvePage = () =>
            resolve({ default: () => <p>the trades page</p> });
        }),
    );
    const router = makeRouter("/trades", [
      { path: "trades", element: <LazyPage /> },
    ]);
    render(<RouterProvider router={router} />);

    expect(
      screen.getByRole("status", { name: TRADES_LOADING_LABEL }),
    ).toBeInTheDocument();
    expect(screen.queryByText("the trades page")).toBeNull();

    await act(async () => {
      resolvePage();
      await Promise.resolve();
    });
    expect(await screen.findByText("the trades page")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: TRADES_LOADING_LABEL }),
    ).toBeNull();
  });

  it("names the loading state for the page it is standing in for", () => {
    const router = makeRouter("/history", [
      {
        path: "history",
        element: (() => {
          const LazyPage = neverResolving();
          return <LazyPage />;
        })(),
      },
    ]);
    render(<RouterProvider router={router} />);
    expect(
      screen.getByRole("status", { name: SEASONS_LOADING_LABEL }),
    ).toBeInTheDocument();
  });

  /**
   * Ben, 2026-09-10: "it does feel like the ui just freezes when switching between things."
   * A navigation is a transition, and inside a transition React keeps the old page on screen
   * while the new one's chunk is fetched — so a tap on a tab did nothing visible until the
   * chunk arrived. The shell has to swap to the destination's loading state at once.
   */
  it("shows the destination's loading state the moment a tab is taken, before its chunk arrives", async () => {
    const LazyPage = neverResolving();
    const router = makeRouter("/", [
      { index: true, element: <p>the board</p> },
      { path: "trades", element: <LazyPage /> },
    ]);
    render(<RouterProvider router={router} />);
    expect(screen.getByText("the board")).toBeInTheDocument();

    await act(async () => {
      await router.navigate("/trades");
    });

    expect(
      screen.getByRole("status", { name: TRADES_LOADING_LABEL }),
    ).toBeInTheDocument();
    expect(screen.queryByText("the board")).toBeNull();
    expect(screen.getByRole("link", { name: "Trades" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("falls back to the board's loading state for any other path", () => {
    const LazyPage = neverResolving();
    const router = makeRouter("/", [{ index: true, element: <LazyPage /> }]);
    render(<RouterProvider router={router} />);
    expect(
      screen.getByRole("status", { name: BOARD_LOADING_LABEL }),
    ).toBeInTheDocument();
  });

  it("prefetches the other pages' chunks once the browser is idle, so a tab opens at once", () => {
    vi.stubGlobal("requestIdleCallback", (callback: () => void) => {
      callback();
      return 1;
    });
    const cancelIdleCallback = vi.fn();
    vi.stubGlobal("cancelIdleCallback", cancelIdleCallback);
    const router = makeRouter("/", [
      { index: true, element: <p>the board</p> },
    ]);
    const { unmount } = render(<RouterProvider router={router} />);
    expect(prefetchPages).toHaveBeenCalledTimes(1);
    // Unmounted here, while the stubs are still in place: the shell cancels its idle request.
    unmount();
    expect(cancelIdleCallback).toHaveBeenCalledWith(1);
  });

  it("prefetches on a timer where the browser has no idle callback", () => {
    vi.stubGlobal("requestIdleCallback", undefined);
    vi.useFakeTimers();
    try {
      const router = makeRouter("/", [
        { index: true, element: <p>the board</p> },
      ]);
      render(<RouterProvider router={router} />);
      expect(prefetchPages).not.toHaveBeenCalled();
      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(prefetchPages).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the three page links, with the current one marked", () => {
    const router = makeRouter("/history", [
      { path: "history", element: <p>history</p> },
    ]);
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

  it("keeps the mute button in the shell, so it is on every page", () => {
    const router = makeRouter("/history", [
      { path: "history", element: <p>history</p> },
    ]);
    render(<RouterProvider router={router} />);
    expect(
      screen.getByRole("button", { name: MUTE_LABEL }),
    ).toBeInTheDocument();
  });
});
