# League Board

## Purpose

Give every league member one phone-sized page that answers "where do I stand right now" without
opening Sleeper: all eighteen teams, sorted by this week's projected points, each showing the
owner, FAAB remaining, record, and an expandable roster. The board is read-only, public, and
live: it re-renders as the Mac mini's sync jobs write new rows to Supabase.

This page uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`
and reads every field through the data layer defined in
`docs/superpowers/specs/2026-09-09-league-data-layer-design.md`. That spec owns the roster,
projection, FAAB, and elimination tables; this spec does not redefine them and adopts whatever
exact names and columns it lands on. The projections sync it describes is pulled forward from
Game Pulse so the board has projections on day one.

The page ships at `/board` in `apps/web`. Recommendation: once it has run for a week and the
projection coverage gate has held, promote it to the home page at `/` and demote today's
`HomePage` to a secondary link, because the board is the only page most members will ever want.
Left as an open question rather than done in the first pass.

## Data

All reads go through `apps/web/src/supabaseClient.ts` with the anon key already in
`apps/web/.env` (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`). The board never calls
`api.sleeper.app` from the browser. The legacy hooks that do (`useLeagueRosters`,
`useLeagueUsers`, `useLeagueGulagData`) and the legacy `player_projections` reads in
`usePlayerProjections.tsx` are not reused; the board's hooks live beside them in
`apps/web/src/queries/` and the legacy hooks are retired separately.

New hooks, one query per table, all keyed by season id and week:

- **Teams and owners.** `public.teams` selecting `id, sleeper_roster_id, team_name, member_id`
  joined to `public.members` for `display_name`, filtered by the active `public.seasons` row.
- **Team week state.** The data layer's per-team state row for the active season, selecting
  team id, FAAB budget remaining, elimination status, and the week the team was eliminated.
- **Team weekly projection.** The data layer's per-team weekly projection row, selecting team
  id, projected points, the projection source and source timestamp, and the coverage fraction
  used for the gate.
- **Record and points.** `public.weekly_results` selecting `week, team_id, points, is_final`
  for the season, aggregated client-side into wins, losses, and points for.
- **Roster holdings.** The data layer's roster slot rows selecting team id, player id, and
  starter flag, joined to `public.players` for `full_name, position, team`, and to the
  per-player weekly projection for projected points.

RLS stays on for every table; the anon role gets `select` only, and only on these public tables.
The board must never read the private schema, phone numbers, member aliases, dues, or any table
carrying message content. Nothing on the page is derived from a private source.

## Live Updates

A single `useLeagueBoardRealtime` hook opens one Supabase Realtime channel subscribed to
postgres changes on the tables above, filtered to the active season where the table carries a
season column. Each event maps to a TanStack Query key and calls `queryClient.invalidateQueries`
for that key only; the hook never writes into the cache directly, so a stale payload can never
overwrite a fresher fetch.

Sync jobs write in bursts (one `ug sleeper sync` pass touches all eighteen rosters). Events are
collected in a ref and flushed on a 750 ms trailing debounce, with a hard ceiling of one flush
per affected query key per second and at most eighteen realtime-triggered refetches per burst
window; anything beyond the ceiling collapses into a single refetch of the whole board. Without
this the page would fire dozens of round trips per sync.

If the channel drops, the hook retries with exponential backoff (1s, 2s, 4s, capped at 30s) and
refetches everything on reconnect, since changes during the gap were missed. Whenever Realtime
is not `SUBSCRIBED`, queries fall back to a 60 second `refetchInterval`; the interval is removed
once the channel is healthy again. Queries also use `refetchOnWindowFocus`, which covers the
common case of a phone waking up.

The sticky header carries an "updated N seconds ago" indicator driven by the newest
`dataUpdatedAt` across the board queries, ticking once a second and switching to minutes past
90 seconds. When the channel is down the indicator gains a muted "reconnecting" label so a stale
number is never presented as live.

## Layout and Interaction

Designed at 375 px first; everything below reads as a single column at that width.

- **Sticky header.** League name, current NFL week, sort control, search field, and the
  last-updated indicator. It stays pinned on scroll and collapses to one line on scroll down.
- **Team cards.** One `Card` per team in a semantic list, sorted by projected points descending.
  Each card shows owner display name, team name, this week's projection as the primary number,
  FAAB remaining, and record with points for. A `Badge` carries the projection caveat when
  coverage is below the gate.
- **Eliminated teams.** Rendered at `opacity-60` with a muted "Eliminated week N" badge, grouped
  after all active teams regardless of the active sort, under a small divider heading.
- **Expansion.** Tapping a card toggles its roster with `Collapsible` from
  `components/ui/collapsible.tsx`. Starters come first under a "Starters" label, then bench.
  Each player line shows name, position, NFL team, and projected points. Only the expanded card
  fetches nothing extra; roster data is already loaded, so expansion is instant.
- **Sort toggles.** Projection, FAAB, and points for, each descending, using `ToggleGroup`.
  Sort state lives in the URL query string so a member can share the view they are looking at.
- **Search.** A single input filtering by owner display name, team name, or player name;
  matching on player name keeps the team card and auto-expands it to the matched player.
- **Dark mode.** Uses the existing `ThemeProvider` in `apps/web/src/main.tsx`
  (`defaultTheme="dark"`, class strategy in `tailwind.config.js`). Only semantic tokens
  (`bg-card`, `text-muted-foreground`, `border`) are used; no hard-coded hex values.
- **Wider screens.** At `sm` the cards go two-up, at `lg` three-up, and the sticky header
  spreads its controls onto one row. `useIsMobile` from `src/lib/hooks/useIsMobile.tsx` is used
  only where behavior differs, not for layout that CSS can express.

## Accessibility

The board is a `<ul>` of `<li>` cards, not a grid of divs. Each card's toggle is a real button
with `aria-expanded` and `aria-controls` pointing at its roster panel; the roster is a nested
list. Focus order follows visual order, and collapsing a card returns focus to its toggle.
Sort toggles are a labeled radio-style group announcing the active sort. The last-updated
indicator is an `aria-live="polite"` region that announces only on a minute boundary, so it does
not chatter. All expansion and reordering animation is wrapped in
`@media (prefers-reduced-motion: reduce)` and reduced to instant state changes. Projection
numbers are never color-only: the caveat is text plus badge.

## Performance

One query per table, no per-team or per-player fetches. Rosters, players, and projections are
joined in memory by id maps built once per data change with `useMemo`; sorting, filtering, and
the eliminated grouping are separate memos keyed on the sort mode and search term so typing does
not re-derive the join. Player rows are memoized components. Search input is debounced 150 ms.
Realtime refetches obey the ceiling above. Target: first meaningful render under 1.5 s on a
mid-tier phone over LTE, and no layout shift when a projection updates in place.

## Empty and Error States

- **Before the first sync.** Skeleton cards from `components/ui/skeleton.tsx` while queries are
  pending; if a table returns zero rows, a plain "Waiting for the first sync" card rather than
  an empty page.
- **Projections unavailable.** When the data layer reports coverage below the 95 percent gate,
  or no projection row exists for the week, the projection number is replaced by an em dash and
  the card shows "Projection unavailable". Sorting falls back to points for and says so. A
  missing projection is never rendered as zero, matching the Game Pulse rule.
- **Partial coverage.** Above zero but below the gate, the number renders with a caveat badge
  reading "Partial projection coverage" and the source timestamp in a tooltip.
- **Realtime disconnected.** A muted banner under the header saying updates are paused and
  polling every 60 seconds, with a manual refresh button. It never blocks the data already shown.
- **Query error.** An `Alert` with the failed section named and a retry button; a failure in one
  query does not blank the rest of the board.

## Privacy and Safety

Everything on the board is public Sleeper data: rosters, projections, FAAB, records, and Sleeper
display names. No phone numbers, no chat content, no dues or payment status, no private schema
tables, no member aliases. The page is unauthenticated by design and must stay safe to share
with anyone, so no field may be added without checking it against that rule. The anon key is the
only credential the bundle carries.

## Test and Rollout

The web app currently has no test runner: `apps/web/package.json` has no `test` script and
neither Vitest nor Playwright is a dependency. Rollout adds Vitest plus
`@testing-library/react` as dev dependencies, a `test` script in `apps/web/package.json`, and a
`test:web` script at the repository root beside the existing `test:agents`.

Unit tests cover the pure derivation and sorting helpers, kept in a separate module from the
components: sort by projection, FAAB, and points descending; missing projection sorted last and
never coerced to zero; eliminated teams grouped last under every sort; record and points-for
aggregation from `weekly_results`; the search matcher across owner, team, and player name; and
the realtime debounce collapsing a burst into the allowed number of refetches.

A Playwright smoke test at a 375 px viewport, asserting eighteen cards render and one expands,
is deferred until Playwright is added to the repository; it is listed as an open item rather
than a blocker. Manual verification before merge: the Vercel preview URL at 375 px in light and
dark mode, one card expanded, and a live sync observed moving the last-updated indicator.

Done means: `/board` renders all eighteen teams from Supabase only, sorts by projection, expands
rosters, updates live within a few seconds of a sync, degrades correctly with projections off,
passes `pnpm lint` and the new unit tests, and is reviewed by Ben on the Vercel preview.

## Out of Scope

- Any write, edit, or admin action; the board is read-only.
- Authentication, per-member views, or anything that requires knowing who is looking.
- Private notes, dues, payment status, and message history.
- Survival odds and elimination predictions, which stay with Game Pulse.
- Trade proposals or advice, which stay with Trade Advisor.
- Retiring the legacy Sleeper-in-the-browser hooks and the old `/rosters` page.

## Open Questions for Ben

1. Should the board become the home page at `/`, or stay at `/board` with a nav link? The
   recommendation is to promote it after a week of live use.
2. Sleeper's projections endpoint is undocumented and its numbers move during game windows. Is
   `pts_ppr` under the league's own `scoring_settings` the right display number, and is a
   "projections from Sleeper, as of <time>" caveat in the header enough, or should the board
   name the provider on every card?
3. Should eliminated teams' rosters stay expandable, freeze at their final roster, or collapse
   permanently once a team is out?
4. `public.members.display_name` currently holds Sleeper usernames. Should the board show those,
   the Sleeper display names, or the nicknames in `private.member_aliases` (which would make the
   page depend on a private table and is not recommended)?

## Decisions from Ben (2026-09-09)

1. The board becomes the home page at `/`. The rest of the old site (rosters, rules, history pages and their direct-Sleeper hooks) is scrapped for now; the router serves only the board.
2. Projections need no heavy caveat. Show the last time the projections were pulled, localized to the viewer and human-readable (for example `Updated 12:41 PM` or `Updated 3 min ago`), instead of provider disclaimers.
3. Eliminated teams' rosters stay expandable. Their final roster is frozen at elimination in the data layer (Sleeper's post-elimination roster state is unreliable once players are dropped), and the board shows that frozen roster with an `eliminated week N` label.
4. Owner names show the nickname from the alias table when one exists, otherwise the Sleeper display name; never the bare Sleeper username. The data layer publishes both as public columns so the board never reads a private table.
5. Injury status is synced. `public.players` gains `injury_status`, written by `ug sleeper players` and carried onto every roster row the board renders. The vocabulary — `Questionable`, `Doubtful`, `Out`, `IR`, `PUP`, `Sus`, `NA`, `COV`, `DNR` — lives in `KNOWN_INJURY_STATUSES` in the sync and in the column's comment, not in a check constraint: a tenth Sleeper value is stored as no flag and counted into the run's report (one `#guillotine-ops` note), because freezing the whole directory over one string is the worse failure. The job moves to every four hours, because the flag is the one thing on the directory that changes mid-week.
6. Out starters are reported as out, not as missing coverage. A starter whose status is `Out`, `IR`, `PUP`, `Sus`, `COV` or `DNR` leaves the coverage denominator exactly as an empty slot already did — and the numerator too, if Sleeper published a number for him anyway — and the card says `N starter(s) out` in the warning token. `partial` is left for a shortfall the injuries do not explain — projected starters over the slots that had a fit player in them, against the same 95 percent gate. `Questionable` and `Doubtful` tag the roster row without taking anyone out of the lineup.
7. The chips sit on a line of their own directly under the owner's name, and the collapsed summary has a fixed height. Out chip first, then `partial`, then `Projection unavailable` and the elimination ruling — every caveat the card carries is a chip on that one line, so no card has a row its neighbour does not. The chip line is a _sibling_ of the summary toggle on the grid's second row, indented to the name's left edge and mounted at a fixed 24px whether it holds two chips or none: a chip can be a real tooltip trigger (hover, focus and tap all open it) without nesting a control inside the button, and the name keeps its whole column. Overlaying the chips on the name's own line was tried and measured out — a 375px phone leaves 109px of name field against a 138.7px two-chip set, so no reserve fits — and the line of its own costs 28px of card height instead, under a summary floor computed from the lines it holds (8rem) that keeps every card in the grid the same height. `partial` is shown when the data layer's own caveat is set and the injuries do not explain it: availability may suppress that verdict, never stand in for it, so a week with no starter counts and a row provisional because the league-wide run was short both keep their chip.
8. The chip set is mutually limited, so a card can only ever carry two short chips. An eliminated card says `Eliminated week N` and nothing else — its projection is not live, so nothing about it needs a caveat — and a card with no projection says only `Projection unavailable`; everywhere else the card says `N starter(s) out` when a starter is out, plus `partial` when the suppression rule leaves it, which is the only two-chip case. That bound is what keeps the chip line to one line — its measured worst case is `2 starters out` + `partial` + the gap, 138.7px in a browser at the chip's 11px face, inside a 225px line — instead of a fallback row below the summary, which had cost every card in the grid 44px to serve a three-chip card that can no longer exist.
