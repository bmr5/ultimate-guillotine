import type { TimeFormatOptions } from "@/board/derive/time";

const SEPARATOR = " · ";

/**
 * The journey's date voice: `Sep 8 · Wk 1`, the day in the viewer's own timezone and Sleeper's
 * own week. The draft entry has no week and reads `Sep 7`. An instant that will not parse
 * loses its day rather than printing `Invalid Date`.
 */
export function formatDateLine(
  iso: string,
  week: number | null,
  options: TimeFormatOptions = {},
): string {
  const parts: string[] = [];
  const at = Date.parse(iso);
  if (Number.isFinite(at)) {
    parts.push(
      new Intl.DateTimeFormat(options.locales, {
        month: "short",
        day: "numeric",
        timeZone: options.timeZone,
      }).format(at),
    );
  }
  if (week !== null) parts.push(`Wk ${week}`);
  return parts.join(SEPARATOR);
}
