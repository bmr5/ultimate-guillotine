import type { TimeFormatOptions } from "@/board/derive/time";

import type { CatalogTrade } from "../types";

/**
 * What separates the two halves of a date line, and the season from the week.
 *
 * One constant for both because they are the same line in two shapes — `Sep 9, 2026 · 9:12 PM`
 * for a trade the Registrar timestamped, `Season 2024 · Week 3` for one the catalog placed by
 * season — and a reader scanning a column of cards should see one punctuation, not two.
 */
const SEPARATOR = " · ";

/**
 * The registered card's stamp: the day, then the clock time, in the viewer's own timezone.
 *
 * `locales` and `timeZone` are left undefined by the card so `Intl` reads the viewer's; tests
 * pass both, because otherwise the expected string depends on the machine running them. That is
 * the arrangement `board/derive/time` already uses, and `TimeFormatOptions` is its type rather
 * than a second copy of it.
 *
 * Two formatters rather than one `dateStyle`/`timeStyle` pair: a combined format joins the two
 * halves with the locale's own connector (`at`, a comma), and the line has to read as the same
 * `·`-separated pair as the catalog's `Season 2024 · Week 3` beside it.
 */
function formatInstant(at: number, options: TimeFormatOptions): string {
  const date = new Intl.DateTimeFormat(options.locales, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: options.timeZone,
  }).format(at);
  const time = new Intl.DateTimeFormat(options.locales, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: options.timeZone,
  }).format(at);
  return `${date}${SEPARATOR}${time}`;
}

/**
 * The one date line a trade card carries, per Ben's ruling of 2026-09-09 that a card logs "the
 * Participants, the date and time, a category, and the exact text".
 *
 * A registered trade was recorded at a known instant, so it says so. A catalog row was read off
 * a spreadsheet that knows a season and a week — or, for a handful of rows, the day it happened
 * — so it keeps saying that instead: `Season 2024 · Week 3` is the most precise thing that row
 * actually knows, and inventing a clock time for it would be a fact the catalog never recorded.
 *
 * An unparseable `registeredAt` falls through to the season form rather than rendering
 * `Invalid Date`. The stamp is a `timestamptz` PostgREST always returns, so this should not
 * happen; a card that quietly loses a line is a better failure than one that prints machine
 * output where a date belongs.
 */
export function tradeDateLine(
  trade: CatalogTrade,
  options: TimeFormatOptions = {},
): string {
  if (trade.registeredAt !== null) {
    const at = Date.parse(trade.registeredAt);
    if (Number.isFinite(at)) return formatInstant(at, options);
  }
  if (trade.week !== null) {
    return `Season ${trade.season}${SEPARATOR}Week ${trade.week}`;
  }
  if (trade.occurredOn !== null) {
    return `Season ${trade.season}${SEPARATOR}${trade.occurredOn}`;
  }
  return `Season ${trade.season}`;
}
