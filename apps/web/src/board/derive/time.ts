/** Every duration below is derived from these, so no bare millisecond literals appear. */
export const MS_PER_SECOND = 1000;
export const SECONDS_PER_MINUTE = 60;
export const MINUTES_PER_HOUR = 60;
export const MS_PER_MINUTE = MS_PER_SECOND * SECONDS_PER_MINUTE;

/** The data layer's staleness threshold: past this, the board shows a stale badge. */
export const STALE_AFTER_MS = 30 * MS_PER_MINUTE;

/**
 * How often the header re-renders the last-pull text. One second is the coarsest tick that
 * still lands every `crossesMinuteBoundary` transition, which is what gates the announcement.
 */
export const TICK_INTERVAL_MS = MS_PER_SECOND;

/** Under this age the relative form says "just now" rather than counting seconds. */
export const JUST_NOW_UNDER_SECONDS = 5;

/** Seconds are counted up to here; past it the relative form switches to whole minutes. */
export const SECONDS_BEFORE_MINUTES = 90;

/** Minutes are counted up to here; past it the relative form switches to whole hours. */
export const MINUTES_BEFORE_HOURS = 90;

/** Shown by every formatter when the board has never completed a pull. */
export const NEVER_UPDATED_LABEL = "Not updated yet";

/**
 * Left undefined in the app so `Intl` uses the viewer's own locale and timezone. Tests pass
 * both explicitly, because otherwise the expected string depends on the machine running them.
 */
export interface TimeFormatOptions {
  locales?: string | string[];
  timeZone?: string;
}

/** Calendar day in the formatting timezone, as a sortable key. */
function dayKey(value: Date, options: TimeFormatOptions): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: options.timeZone,
  }).format(value);
}

/**
 * The primary last-pull text: the absolute time the projections were pulled, localized to the
 * viewer. A pull made today is just the clock time; anything older carries its date, because
 * `Updated 12:41 PM` on a three-day-old pull would read as fresh.
 */
export function formatUpdatedAt(
  updatedAt: number | null,
  now: number,
  options: TimeFormatOptions = {},
): string {
  if (updatedAt === null) {
    return NEVER_UPDATED_LABEL;
  }
  const then = new Date(updatedAt);
  const time = new Intl.DateTimeFormat(options.locales, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: options.timeZone,
  }).format(then);
  if (dayKey(then, options) === dayKey(new Date(now), options)) {
    return `Updated ${time}`;
  }
  const date = new Intl.DateTimeFormat(options.locales, {
    month: "short",
    day: "numeric",
    timeZone: options.timeZone,
  }).format(then);
  return `Updated ${date}, ${time}`;
}

/**
 * The hover/`title` form: the same instant spelled out in full, still localized. The raw ISO
 * timestamp is never surfaced — it reads as machine output and is in the wrong timezone.
 */
export function formatUpdatedTitle(
  updatedAt: number | null,
  options: TimeFormatOptions = {},
): string {
  if (updatedAt === null) {
    return NEVER_UPDATED_LABEL;
  }
  const full = new Intl.DateTimeFormat(options.locales, {
    dateStyle: "full",
    timeStyle: "short",
    timeZone: options.timeZone,
  }).format(new Date(updatedAt));
  return `Updated ${full}`;
}

/** The secondary form, shown smaller beside the absolute time. */
export function formatUpdatedAgo(updatedAt: number | null, now: number): string {
  if (updatedAt === null) {
    return "never";
  }
  const seconds = Math.floor(Math.max(0, now - updatedAt) / MS_PER_SECOND);
  if (seconds < JUST_NOW_UNDER_SECONDS) {
    return "just now";
  }
  if (seconds < SECONDS_BEFORE_MINUTES) {
    return `${seconds} sec ago`;
  }
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  if (minutes < MINUTES_BEFORE_HOURS) {
    return `${minutes} min ago`;
  }
  return `${Math.floor(minutes / MINUTES_PER_HOUR)} hr ago`;
}

export function isStale(
  updatedAt: number | null,
  now: number,
  thresholdMs: number = STALE_AFTER_MS,
): boolean {
  if (updatedAt === null) {
    return true;
  }
  return now - updatedAt > thresholdMs;
}

/**
 * The last-pull indicator ticks every second but is an aria-live region, so it
 * must only announce when the spoken text actually changes — once a minute.
 */
export function crossesMinuteBoundary(
  previousElapsedMs: number,
  nextElapsedMs: number,
): boolean {
  return Math.floor(previousElapsedMs / MS_PER_MINUTE) !== Math.floor(nextElapsedMs / MS_PER_MINUTE);
}
