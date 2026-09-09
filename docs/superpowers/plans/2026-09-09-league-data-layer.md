# League Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Sleeper facts every downstream feature needs — roster holdings, FAAB and record, weekly player projections, team projected points, the frozen final roster of every eliminated team, the label each owner is known by, and the NFL week — into first-class Supabase rows written by three script-only cron jobs, so the board, the bot, and the agents all read the same numbers.

**Architecture:** One migration adds six `public` tables, four cached columns on `public.seasons`, and the two owner-label columns on `public.members`, publishes the five board-facing tables to Supabase Realtime, and grants `delete` on the single current-state cache. Pure Python functions do all the interesting work — slot classification, FAAB recombination, the scoring dot product, coverage arithmetic, elimination precedence, the final-roster payload — and thin repositories upsert their output on natural keys inside one transaction per job. Three `ug sleeper` subcommands (`sync` extended, `projections` and `state` new) are the only writers of Sleeper facts, and `ug members aliases load` is the only writer of `members.nickname`; each scheduled one is wrapped in `run_scheduled`.

**Tech Stack:** Python 3.12, Pydantic 2.13.5, psycopg 3.3.5, httpx 0.28.1 with respx 0.23.1, `decimal.Decimal` for money and points, Supabase migrations with pgTAP, Hermes cron on the `guillotine` profile.

**Spec:** `docs/superpowers/specs/2026-09-09-league-data-layer-design.md`, which inherits `docs/superpowers/specs/2026-08-27-automation-foundation-design.md` (revision 2026-09-08).

## Global Constraints

- Every table lives in `public`, with an identity primary key, `created_at timestamptz not null default now()`, RLS enabled, `revoke all` then `grant select` to `anon, authenticated`, a `"Public <table> are readable"` policy, and an `"Automation writes <table>"` policy `for all to automation_worker using (true) with check (true)` plus matching grants. One migration: `supabase/migrations/<timestamp>_league_data_layer.sql`.
- `automation_worker` gains `delete` on `public.roster_holdings` **and on no other table**. Every other public table stays insert/update-only.
- Every write is an upsert on a natural key: `roster_holdings` on `(season_id, team_id, sleeper_player_id)`, `team_season_state` on `(season_id, team_id)`, `player_projections` on `(season, week, sleeper_player_id)`, `team_week_projections` on `(season_id, team_id, week)`, `nfl_state` on the constant `id = 1`. Repeated runs with the same input produce byte-identical rows.
- `public.roster_holdings` is the only table that deletes: rows for a synced team whose player id was not in the fetched set are deleted in the same transaction as the upserts.
- `public.final_rosters` is written **exactly once** per `(season_id, team_id)`, with `on conflict (season_id, team_id) do nothing`. A snapshot is never updated, never deleted, and never overwritten by a later sync. Later syncs still update `roster_holdings` for an eliminated team — managers go on dropping and adding after they are out — so consumers read `final_rosters` for any team whose `team_season_state.is_eliminated` is true and `roster_holdings` for everybody else.
- Consumers label an owner by `public.members.nickname`, falling back to `public.members.sleeper_display_name` when the nickname is null. The bare Sleeper username is never shown, and `members.display_name` is a matching key, not a label: nothing renders it.
- Every week-scoped job reads the week from `public.nfl_state`, never from the clock. If that row is missing or its `synced_at` is older than 60 minutes, the job refreshes it inline before continuing.
- The coverage gate is 95 percent, evaluated once per projections run over all filled starter slots of all non-eliminated teams. Below the gate rows are still written, flagged never withheld.
- `league_points` is null when the stat line cannot be scored at all. A null is a missing projection, never a zero.
- Elimination precedence: `elimination_source = 'adjudicator'` is authoritative and is never overwritten by `'sleeper_inferred'`. `state_version` increments only when `is_eliminated` or `eliminated_week` changes.
- A Sleeper outage, timeout, or non-2xx aborts the job's transaction; the last good rows survive untouched and `synced_at` stops advancing.
- Everything in this layer is public Sleeper data. Never log, print, or persist member phone numbers, chat GUIDs, message bodies, or any private contact detail. No table here has a per-member visibility rule.
- All commands run from the repository root with `uv run --project packages/league-automation ...`; `pnpm test:agents` and `pnpm lint:agents` are the suite commands. DB-backed tests use the shared `conn` fixture in `packages/league-automation/tests/conftest.py` and require `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres`. Follow TDD. Ruff line length is 100.
- Commit after each task with a conventional message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Consumers

No consumer is built by this plan; these are the read contracts the tables are shaped for, and the rules a consumer must follow once they exist.

- **League board (`apps/web`)**: `teams` and `members` for the 18 rows, `team_week_projections` for the sort key and the displayed projection (`is_provisional` renders "projection unavailable"), `team_season_state` for FAAB remaining, record, and elimination, `roster_holdings` joined to `players` and `player_projections` for a live team's expandable roster, `final_rosters.holdings` for an eliminated team's, `nfl_state` for the week. Realtime on all five published tables. This retires the direct-from-browser `useLeagueRosters`, `useLeagueUsers`, and `useLeagueGulagData` hooks and the legacy FantasyData `fpts_ppr` shape.
- **Trade Advisor**: `roster_holdings` plus `players` for holdings and positional surplus, `player_projections` for value over the next weeks, `team_season_state` for FAAB capacity and guillotine pressure, `trades` and `trade_revisions` for history, `nfl_state` for the horizon.
- **League Concierge data questions**: `team_week_projections` for comparisons and "bottom 5 right now", `team_season_state`, `roster_holdings`, `final_rosters`, `nfl_state`; every answer cites `synced_at`.
- **Game Pulse**: `player_projections` as the Monte Carlo input, `roster_holdings` filtered to `slot = 'starter'` for remaining starters, `team_week_projections.coverage_pct` for its 95 percent gate, `nfl_state` for the week.
- **Weekly Adjudicator**: unchanged owner of `weekly_results` and elimination `league_events`; reads `team_season_state` only to detect drift and writes the authoritative elimination back. Its ruling is what the next `ug sleeper sync` freezes into `final_rosters`.
- **Trade Registrar**: `build_roster_index`, which reads `roster_holdings` (Task 11).
- **Every consumer, every surface**: an eliminated team is shown its `final_rosters.holdings`, never its live `roster_holdings`; an owner is labelled `members.nickname` else `members.sleeper_display_name`; an `elimination_source` of `'sleeper_inferred'` is labelled provisional.

## Verified External Interfaces

Sleeper, read live on 2026-09-09 from this repository's league (`1389372259260452864`):

- `GET https://api.sleeper.app/v1/state/nfl` returns
  `{"week":1,"leg":1,"season_type":"regular","season":"2026","league_season":"2026","previous_season":"2025","season_start_date":"2026-09-09","display_week":1,"league_create_season":"2026","season_has_scores":true}`.
  `season` and `previous_season` are **strings**, not integers.
- `GET https://api.sleeper.app/v1/league/{league_id}` returns `roster_positions`
  (`["QB","RB","RB","WR","WR","TE","FLEX","K","DEF"]` — nine slots),
  `scoring_settings` (128 float-valued keys including `pass_yd: 0.04`, `pass_td: 4.0`,
  `pass_int: -1.0`, `rec: 1.0`, `rec_yd: 0.1`, `rec_td: 6.0`, `rush_td: 6.0`,
  `fum_lost: -2.0`, `bonus_rec_te: 0.0`, `pts_allow_14_20: 1.0`), and
  `settings.waiver_budget: 1000`.
- **The projections endpoint (undocumented, verified by one real `curl` in Task 1):**
  `GET https://api.sleeper.app/projections/nfl/2026/1?season_type=regular` → HTTP 200,
  5,670,117 bytes, a **JSON array** (not an object keyed by player id) of 9,419 objects,
  one per player, no duplicate `player_id`. Each object has keys
  `status, date, stats, category, last_modified, week, season, season_type, sport, player, team, player_id, opponent, updated_at, game_id, week_shard, company`.
  `category` is `"proj"` on every row, `company` is `"rotowire"` on every row, `week` is an
  int, `season` and `season_type` are strings, `player_id` is a string (`"4943"`, or a team
  code such as `"SEA"` for a defense), `updated_at` and `last_modified` are epoch
  milliseconds, `stats` is a flat map of float stat keys, and `player` is a nested object
  with `first_name`, `last_name`, `position`, `team`. No row had an empty `stats` map.
  The `stats` keys are the **same keys** `scoring_settings` uses, which is what makes the
  dot product exact.

Existing repository interfaces this plan builds on (do not redefine):

- `ultimate_guillotine.sleeper.client.SleeperClient(http)` with `get_league`, `get_users`, `get_rosters`, `get_matchups`, `get_nfl_state`, `get_players`. `BASE_URL = "https://api.sleeper.app/v1"`, `TIMEOUT = 10.0`, `follow_redirects = False`.
- `ultimate_guillotine.sleeper.models.SleeperRoster(roster_id, owner_id, players)` with the `_no_players_is_an_empty_roster` before-validator.
- `ultimate_guillotine.sleeper.sync.sync_season(client, conn, year, league_id) -> SyncReport(members, teams)`, which fetches before opening `conn.transaction()` and validates against `seasons.expected_rosters`.
- `ultimate_guillotine.sleeper.players.PlayerRepository`, `Player`, `sync_players`.
- `ultimate_guillotine.cli.deps.build_deps() -> Deps(settings, conn, client, notifier)` and `run_scheduled(conn, agent, now, action, trigger="cron", idempotency_key=None)`.
- `ultimate_guillotine.data.repositories.RunRepository(conn)` with `reserve`, `finish`, `stale_running`, `last_started`; `SeasonRepository(conn).current()`.
- `ultimate_guillotine.ops.notify.HermesNotifier` with `.ops(text)`, `.feed`, `.drafts`, `.alerts`.
- `ultimate_guillotine.trades.resolve.RosterIndex(holdings)`, `.empty()`, `.holds(member_id, player_id)`, and `build_roster_index(client, conn, league_id, season)`.
- `hermes/guillotine/cron.yaml` job shape (`name`, `agent`, `schedule`, `script`, `deliver`, `max_gap_minutes`), `hermes/guillotine/scripts/*.sh.template` with the `__REPO__` placeholder, and `hermes/guillotine/install.sh`, which copies every template and runs `register_cron.py` then `ug ops sync-expected-runs`.

## File Structure

```text
packages/league-automation/src/ultimate_guillotine/
  sleeper/client.py            # + get_projections(season, week): absolute URL, outside /v1
  sleeper/models.py            # SleeperRoster + starters/reserve/taxi/settings/metadata
  sleeper/scoring.py           # pure: score_stat_line, scoring_version, preset_drift
  sleeper/roster_state.py      # pure: classify_holdings, team_state_from_roster,
                               #   merge_elimination, holdings_payload +
                               #   RosterHoldingRepository, TeamStateRepository,
                               #   FinalRosterRepository
  sleeper/state.py             # NflState, parse_nfl_state, NflStateRepository, current_week
  sleeper/projections.py       # ProjectionRow, load_projections, ProjectionRepository,
                               #   sync_projections
  sleeper/team_projections.py  # TeamWeekProjection, compute_team_week, run_coverage,
                               #   TeamWeekRepository, recompute_team_week
  sleeper/sync.py              # sync_season writes season settings, holdings, team
                               #   state, owner display names, and the one-time freeze
  trades/resolve.py            # build_roster_index reads roster_holdings, falls back
  ops/transitions.py           # pure: transition_note (one ops note per status change)
  cli/sleeper.py               # + ug sleeper projections, ug sleeper state
  cli/members.py               # ug members list flags who has a nickname
  data/repositories.py         # MemberAliasRepository writes members.nickname
  trades/models.py             # MemberRef gains has_nickname
supabase/migrations/<ts>_league_data_layer.sql
supabase/tests/league_data_layer.sql
hermes/guillotine/cron.yaml
hermes/guillotine/scripts/guillotine_sleeper_projections.sh.template
hermes/guillotine/scripts/guillotine_nfl_state.sh.template
packages/league-automation/tests/
  fixtures/sleeper/projections_2026_w1.json   # trimmed from the real curl (Task 1)
  fixtures/sleeper/league_2026.json           # + scoring_settings, roster_positions,
                                              #   settings.waiver_budget
  fixtures/sleeper/rosters_2026.json          # + starters/reserve/taxi/settings/metadata
  sleeper/test_scoring.py, test_roster_state.py, test_state.py,
  sleeper/test_projections.py, test_team_projections.py, test_sync_league_data.py,
  sleeper/test_final_rosters.py,
  ops/test_transitions.py, trades/test_roster_index.py, cli/test_sleeper.py,
  data/test_repositories.py, cli/test_members.py    # extended, not created
```

---

### Task 1: Verify the projections endpoint and add `get_projections`

**Files:**
- Create: `packages/league-automation/tests/fixtures/sleeper/projections_2026_w1.json`
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/client.py`
- Create: `packages/league-automation/tests/sleeper/test_projections_client.py`

**Interfaces:**
- Consumes: `SleeperClient`, `httpx`, `respx`.
- Produces:
  - `PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"` in `sleeper/client.py`.
  - `SleeperClient.get_projections(season: int, week: int) -> list[dict[str, Any]]` — issues an **absolute** URL because the endpoint sits outside `/v1`, with `params={"season_type": "regular"}` and `timeout=60.0`, keeping the client's pinned `follow_redirects = False`. Raises for non-2xx. Raises `ValueError` when the payload is not a list.

- [ ] **Step 1: Re-run the verification curl and record it**

Run exactly this, from the repository root:

```bash
curl -s -o /tmp/proj.json -w "HTTP:%{http_code} SIZE:%{size_download}\n" \
  "https://api.sleeper.app/projections/nfl/2026/1?season_type=regular"
python3 -c "
import json, collections
d = json.load(open('/tmp/proj.json'))
print(type(d).__name__, len(d))
print(sorted(d[0].keys()))
print(collections.Counter(r['category'] for r in d))
print(len({r['player_id'] for r in d}))
"
```

Expected, matching the recording in **Verified External Interfaces** above: `HTTP:200`,
roughly 5.6 MB, `list 9419`, the seventeen keys
`['category', 'company', 'date', 'game_id', 'last_modified', 'opponent', 'player', 'player_id', 'season', 'season_type', 'sport', 'stats', 'status', 'team', 'updated_at', 'week', 'week_shard']`,
`Counter({'proj': 9419})`, and `9419` distinct player ids. If the shape has changed since
2026-09-09, stop and report the difference before writing any code — every later task
parses this shape.

- [ ] **Step 2: Write the fixture**

Create `packages/league-automation/tests/fixtures/sleeper/projections_2026_w1.json` with
these six rows, copied verbatim from the live payload (QB, RB, WR, TE, K, DEF, plus one
IDP-only row whose stat keys the league does not score). `player` sub-objects are trimmed
to the four fields any consumer reads.

```json
[
  {
    "player_id": "4943", "team": "SEA", "opponent": "NE", "date": "2026-09-09",
    "week": 1, "season": "2026", "season_type": "regular", "sport": "nfl",
    "category": "proj", "company": "rotowire", "status": null,
    "game_id": "202610130", "week_shard": "1_5",
    "updated_at": 1788963030547, "last_modified": 1788963030547,
    "player": {"first_name": "Sam", "last_name": "Darnold", "position": "QB", "team": "SEA"},
    "stats": {
      "adp_dd_ppr": 117.0, "cmp_pct": 63.77, "fum": 0.43, "fum_lost": 0.19, "gp": 1.0,
      "pass_2pt": 0.1, "pass_att": 32.56, "pass_cmp": 20.76, "pass_int": 0.9,
      "pass_td": 1.71, "pass_yd": 243.94, "pts_half_ppr": 17.11, "pts_ppr": 17.11,
      "pts_std": 17.11, "rush_att": 2.92, "rush_td": 0.1, "rush_yd": 9.79
    }
  },
  {
    "player_id": "7611", "team": "NE", "opponent": "SEA", "date": "2026-09-09",
    "week": 1, "season": "2026", "season_type": "regular", "sport": "nfl",
    "category": "proj", "company": "rotowire", "status": null,
    "game_id": "202610130", "week_shard": "1_5",
    "updated_at": 1788963030551, "last_modified": 1788963030551,
    "player": {"first_name": "Rhamondre", "last_name": "Stevenson", "position": "RB",
               "team": "NE"},
    "stats": {
      "adp_dd_ppr": 20.0, "bonus_rec_rb": 2.94, "fum_lost": 0.07, "gp": 1.0, "rec": 2.94,
      "rec_td": 0.12, "rec_yd": 20.57, "rush_att": 16.66, "rush_td": 0.59,
      "rush_yd": 72.39, "pts_half_ppr": 14.96, "pts_ppr": 16.43, "pts_std": 13.49
    }
  },
  {
    "player_id": "9488", "team": "SEA", "opponent": "NE", "date": "2026-09-09",
    "week": 1, "season": "2026", "season_type": "regular", "sport": "nfl",
    "category": "proj", "company": "rotowire", "status": null,
    "game_id": "202610130", "week_shard": "1_5",
    "updated_at": 1788963030549, "last_modified": 1788963030549,
    "player": {"first_name": "Jaxon", "last_name": "Smith-Njigba", "position": "WR",
               "team": "SEA"},
    "stats": {
      "adp_dd_ppr": 7.0, "bonus_rec_wr": 6.83, "fum_lost": 0.03, "gp": 1.0, "rec": 6.83,
      "rec_td": 0.53, "rec_yd": 94.17, "rush_yd": 1.85, "pts_half_ppr": 16.28,
      "pts_ppr": 19.69, "pts_std": 12.86
    }
  },
  {
    "player_id": "12517", "team": "CHI", "opponent": "MIN", "date": "2026-09-13",
    "week": 1, "season": "2026", "season_type": "regular", "sport": "nfl",
    "category": "proj", "company": "rotowire", "status": null,
    "game_id": "202610101", "week_shard": "1_1",
    "updated_at": 1788963030553, "last_modified": 1788963030553,
    "player": {"first_name": "Colston", "last_name": "Loveland", "position": "TE",
               "team": "CHI"},
    "stats": {
      "adp_dd_ppr": 27.0, "bonus_rec_te": 5.1, "fum_lost": 0.02, "gp": 1.0, "rec": 5.1,
      "rec_td": 0.46, "rec_yd": 62.78, "pts_half_ppr": 11.62, "pts_ppr": 14.17,
      "pts_std": 9.07
    }
  },
  {
    "player_id": "12713", "team": "NE", "opponent": "SEA", "date": "2026-09-09",
    "week": 1, "season": "2026", "season_type": "regular", "sport": "nfl",
    "category": "proj", "company": "rotowire", "status": null,
    "game_id": "202610130", "week_shard": "1_5",
    "updated_at": 1788963030555, "last_modified": 1788963030555,
    "player": {"first_name": "Andy", "last_name": "Borregales", "position": "K",
               "team": "NE"},
    "stats": {
      "adp_dd_ppr": 999.0, "fga": 1.99, "fgm": 1.64, "fgm_0_19": 0.05, "fgm_20_29": 0.25,
      "fgm_30_39": 0.45, "fgm_40_49": 0.4, "fgm_yds": 44.07, "gp": 1.0, "xpm": 2.4,
      "pts_half_ppr": 6.1, "pts_ppr": 6.1, "pts_std": 6.1
    }
  },
  {
    "player_id": "SEA", "team": "SEA", "opponent": "NE", "date": "2026-09-09",
    "week": 1, "season": "2026", "season_type": "regular", "sport": "nfl",
    "category": "proj", "company": "rotowire", "status": null,
    "game_id": "202610130", "week_shard": "1_5",
    "updated_at": 1788963030557, "last_modified": 1788963030557,
    "player": {"first_name": "Seattle", "last_name": "Seahawks", "position": "DEF",
               "team": "SEA"},
    "stats": {
      "adp_dd_ppr": 999.0, "blk_kick": 0.05, "def_td": 0.21, "ff": 0.78, "fum_rec": 0.57,
      "gp": 1.0, "int": 0.83, "pts_allow": 20.75, "pts_allow_14_20": 1.0, "sack": 2.45,
      "safe": 0.05, "pts_half_ppr": 8.81, "pts_ppr": 8.81, "pts_std": 8.81
    }
  },
  {
    "player_id": "10881", "team": "NE", "opponent": "SEA", "date": "2026-09-09",
    "week": 1, "season": "2026", "season_type": "regular", "sport": "nfl",
    "category": "proj", "company": "rotowire", "status": null,
    "game_id": "202610130", "week_shard": "1_5",
    "updated_at": 1788963030535, "last_modified": 1788963030535,
    "player": {"first_name": "Christian", "last_name": "Gonzalez", "position": "DB",
               "team": "NE"},
    "stats": {
      "adp_dd_ppr": 999.0, "gp": 1.0, "idp_int": 0.11, "idp_tkl": 2.98,
      "idp_tkl_ast": 0.49, "idp_tkl_solo": 2.5, "pts_half_ppr": 0.22, "pts_ppr": 0.22,
      "pts_std": 0.22
    }
  }
]
```

- [ ] **Step 3: Write the failing test**

```python
# packages/league-automation/tests/sleeper/test_projections_client.py
import json
from pathlib import Path

import httpx
import pytest
import respx

from ultimate_guillotine.sleeper.client import SleeperClient

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "projections_2026_w1.json"
URL = "https://api.sleeper.app/projections/nfl/2026/1"


@respx.mock
def test_get_projections_uses_the_absolute_non_v1_url_and_regular_season_type() -> None:
    route = respx.get(URL).mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    rows = SleeperClient(httpx.Client()).get_projections(2026, 1)
    assert isinstance(rows, list) and len(rows) == 7
    assert {r["player_id"] for r in rows} >= {"4943", "SEA", "10881"}
    assert rows[0]["stats"]["pass_yd"] == 243.94
    request = route.calls.last.request
    assert str(request.url) == f"{URL}?season_type=regular"
    assert "/v1/" not in str(request.url)


@respx.mock
def test_get_projections_raises_on_non_2xx() -> None:
    respx.get(URL).mock(return_value=httpx.Response(502))
    with pytest.raises(httpx.HTTPStatusError):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_non_list_payload() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"4943": {}}))
    with pytest.raises(ValueError, match="list"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)
```

- [ ] **Step 4: Run the test red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_projections_client.py -v`

Expected: FAIL with `AttributeError: 'SleeperClient' object has no attribute 'get_projections'`.

- [ ] **Step 5: Implement**

Add to `sleeper/client.py`, below `BASE_URL`:

```python
#: Sleeper's projections live outside the versioned API, so this one call uses an
#: absolute URL instead of the client's pinned ``base_url``. Verified 2026-09-09.
PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"
```

and as a method on `SleeperClient`:

```python
    def get_projections(self, season: int, week: int) -> list[dict[str, Any]]:
        """Fetch weekly player projections for ``season``/``week``.

        The endpoint sits outside ``/v1`` and answers with a JSON array of one
        object per player (roughly 9,400 rows, 5.6 MB), so it gets an absolute
        URL and the same longer timeout the player dump uses. Redirects stay
        disabled by the client's constructor.
        """
        response = self._http.get(
            PROJECTIONS_URL.format(season=season, week=week),
            params={"season_type": "regular"},
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("sleeper projections payload is not a list")
        return payload
```

- [ ] **Step 6: Run green, lint, commit**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_projections_client.py -v && pnpm lint:agents`

Expected: 3 passed.

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/client.py \
        packages/league-automation/tests/sleeper/test_projections_client.py \
        packages/league-automation/tests/fixtures/sleeper/projections_2026_w1.json
git commit -m "feat: fetch Sleeper weekly projections from the non-v1 endpoint"
```

### Task 2: Migration and pgTAP for the six tables

**Files:**
- Create through CLI: `supabase/migrations/<generated>_league_data_layer.sql`
- Create: `supabase/tests/league_data_layer.sql`

**Interfaces:**
- Consumes: `public.seasons`, `public.teams` from `20260908204333_public_league_schema.sql`; the `automation_worker` role and the `"Automation writes <table>"` convention from `20260908234819_automation_worker_public_policies.sql`.
- Produces: columns `public.seasons.scoring_settings`, `.roster_positions`, `.waiver_budget`, `.league_synced_at`; columns `public.members.sleeper_display_name` and `.nickname`; tables `public.roster_holdings`, `public.team_season_state`, `public.final_rosters`, `public.player_projections`, `public.team_week_projections`, `public.nfl_state`; `delete` on `public.roster_holdings` for `automation_worker` and on no other public table; membership of five tables in the `supabase_realtime` publication; `replica identity full` on `public.roster_holdings`.

- [ ] **Step 1: Create the migration file**

Run: `supabase migration new league_data_layer`

Write this into the generated file:

```sql
-- League data layer: roster holdings, team season state, the frozen final roster of an
-- eliminated team, player and team-week projections, and the single NFL state row, plus
-- the two owner-label columns on public.members. Same shape as the nine existing public
-- tables: identity key, created_at, RLS on, select-only for anon/authenticated, and an
-- "Automation writes <table>" policy for automation_worker.

-- The league's own settings are cached on the season row rather than in a settings
-- table: there is one row per year and every consumer already joins to it.
alter table public.seasons
  add column scoring_settings jsonb not null default '{}',
  add column roster_positions jsonb not null default '[]',
  add column waiver_budget int,
  add column league_synced_at timestamptz;

-- How an owner is labelled. members.display_name stays the natural key that sync upserts
-- on and that the alias file's sleeper_username matches; it is never rendered.
-- sleeper_display_name is refreshed from Sleeper's user record on every sync, and
-- nickname is written by `ug members aliases load` from the member's first alias.
-- Both are anon-readable because the public board renders them; every other alias stays
-- in private.member_aliases, which anon cannot reach.
alter table public.members
  add column sleeper_display_name text,
  add column nickname text;

-- Current-state cache of who holds whom. No foreign key to public.players on purpose:
-- Sleeper rosters carry ids the filtered skill-position directory drops.
create table public.roster_holdings (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  sleeper_player_id text not null,
  slot text not null check (slot in ('starter', 'bench', 'ir', 'taxi')),
  slot_index int,
  lineup_position text,
  synced_at timestamptz not null,
  unique (season_id, team_id, sleeper_player_id)
);
create index roster_holdings_season_player_idx
  on public.roster_holdings (season_id, sleeper_player_id);
create index roster_holdings_team_id_idx on public.roster_holdings (team_id);

create table public.team_season_state (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  faab_budget int not null,
  faab_used int not null,
  faab_remaining int generated always as (faab_budget - faab_used) stored,
  wins int not null default 0,
  losses int not null default 0,
  ties int not null default 0,
  points_for numeric(10, 2) not null default 0,
  points_against numeric(10, 2) not null default 0,
  is_eliminated boolean not null default false,
  eliminated_week int,
  elimination_source text
    check (elimination_source in ('adjudicator', 'sleeper_inferred', 'manual')),
  state_version int not null default 1,
  synced_at timestamptz not null,
  unique (season_id, team_id)
);
create index team_season_state_team_id_idx on public.team_season_state (team_id);

-- The roster a team was eliminated with, captured once and never rewritten.
-- roster_holdings keeps following Sleeper after a team is out, because managers go on
-- dropping and adding, so the holdings at the moment of elimination are frozen here.
-- holdings is the classify_holdings output verbatim: a JSON array of
-- {sleeper_player_id, slot, slot_index, lineup_position}, in lineup order.
-- eliminated_week is nullable because a provisional Sleeper-inferred elimination may not
-- know the week yet; the snapshot is still taken, because the roster is what changes.
create table public.final_rosters (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  eliminated_week int,
  holdings jsonb not null,
  frozen_at timestamptz not null,
  unique (season_id, team_id)
);
create index final_rosters_season_idx on public.final_rosters (season_id);

-- Keyed by the plain season year, not season_id: a projection is a property of the NFL
-- week, not of this league. stat_line keeps Sleeper's raw map so a scoring change can be
-- replayed without refetching.
create table public.player_projections (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season int not null,
  week int not null,
  sleeper_player_id text not null,
  stat_line jsonb not null,
  league_points numeric(8, 2),
  pts_ppr numeric(8, 2),
  pts_half_ppr numeric(8, 2),
  pts_std numeric(8, 2),
  scoring_version text not null,
  source text not null default 'sleeper',
  coverage_flagged boolean not null default false,
  run_coverage_pct numeric(5, 2),
  projected_at timestamptz not null,
  synced_at timestamptz not null,
  unique (season, week, sleeper_player_id)
);
create index player_projections_season_week_idx on public.player_projections (season, week);
create index player_projections_player_idx on public.player_projections (sleeper_player_id);

-- A written table, not a view: Realtime publishes tables only, and the board's sort key
-- should be one indexed read.
create table public.team_week_projections (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  week int not null,
  projected_points numeric(8, 2) not null,
  starter_slots int not null,
  filled_slots int not null,
  empty_slots int not null,
  starters_projected int not null,
  missing_projections int not null,
  coverage_pct numeric(5, 2) not null,
  is_provisional boolean not null default false,
  computed_at timestamptz not null,
  unique (season_id, team_id, week)
);
create index team_week_projections_season_week_idx
  on public.team_week_projections (season_id, week);

create table public.nfl_state (
  id int primary key default 1 check (id = 1),
  created_at timestamptz not null default now(),
  season int not null,
  season_type text not null,
  week int not null,
  display_week int,
  leg int,
  previous_season int,
  season_start_date date,
  raw jsonb not null,
  synced_at timestamptz not null
);

alter table public.roster_holdings enable row level security;
alter table public.team_season_state enable row level security;
alter table public.final_rosters enable row level security;
alter table public.player_projections enable row level security;
alter table public.team_week_projections enable row level security;
alter table public.nfl_state enable row level security;

revoke all on public.roster_holdings from anon, authenticated;
revoke all on public.team_season_state from anon, authenticated;
revoke all on public.final_rosters from anon, authenticated;
revoke all on public.player_projections from anon, authenticated;
revoke all on public.team_week_projections from anon, authenticated;
revoke all on public.nfl_state from anon, authenticated;

grant select on public.roster_holdings to anon, authenticated;
grant select on public.team_season_state to anon, authenticated;
grant select on public.final_rosters to anon, authenticated;
grant select on public.player_projections to anon, authenticated;
grant select on public.team_week_projections to anon, authenticated;
grant select on public.nfl_state to anon, authenticated;

create policy "Public roster_holdings are readable" on public.roster_holdings
  for select using (true);
create policy "Public team_season_state are readable" on public.team_season_state
  for select using (true);
create policy "Public final_rosters are readable" on public.final_rosters
  for select using (true);
create policy "Public player_projections are readable" on public.player_projections
  for select using (true);
create policy "Public team_week_projections are readable" on public.team_week_projections
  for select using (true);
create policy "Public nfl_state are readable" on public.nfl_state for select using (true);

create policy "Automation writes roster_holdings" on public.roster_holdings
  for all to automation_worker using (true) with check (true);
create policy "Automation writes team_season_state" on public.team_season_state
  for all to automation_worker using (true) with check (true);
create policy "Automation writes final_rosters" on public.final_rosters
  for all to automation_worker using (true) with check (true);
create policy "Automation writes player_projections" on public.player_projections
  for all to automation_worker using (true) with check (true);
create policy "Automation writes team_week_projections" on public.team_week_projections
  for all to automation_worker using (true) with check (true);
create policy "Automation writes nfl_state" on public.nfl_state
  for all to automation_worker using (true) with check (true);

grant select, insert, update on public.roster_holdings to automation_worker;
grant select, insert, update on public.team_season_state to automation_worker;
-- final_rosters gets the same insert/update grant as its neighbours for consistency, but
-- nothing ever updates it: FinalRosterRepository.freeze is insert-or-do-nothing, and the
-- unique (season_id, team_id) constraint is what makes a snapshot permanent.
grant select, insert, update on public.final_rosters to automation_worker;
grant select, insert, update on public.player_projections to automation_worker;
grant select, insert, update on public.team_week_projections to automation_worker;
grant select, insert, update on public.nfl_state to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;

-- roster_holdings is a cache, not a league fact: a dropped player must vanish. This is
-- the only public table automation_worker may delete from.
grant delete on table public.roster_holdings to automation_worker;

-- Realtime. final_rosters is published so an open board swaps an eliminated team's
-- roster the moment the freeze lands, without a refresh. player_projections is
-- deliberately excluded: a run touches thousands of rows and would flood every open
-- board. The board fetches a team's player projections on expand and re-fetches when
-- that team's row changes.
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
end
$$;

alter publication supabase_realtime add table public.roster_holdings;
alter publication supabase_realtime add table public.team_season_state;
alter publication supabase_realtime add table public.final_rosters;
alter publication supabase_realtime add table public.team_week_projections;
alter publication supabase_realtime add table public.nfl_state;

-- The primary-key default is enough for the four tables that only insert and update.
-- roster_holdings deletes, and the client needs the old row's team_id and
-- sleeper_player_id to evict it from cache. Roughly 18 teams times 20 players, so the
-- extra WAL is negligible.
alter table public.roster_holdings replica identity full;

-- public.player_projections supersedes the foundation's planned snapshot table, which
-- shipped empty and is referenced by no code.
drop table if exists private.projection_snapshots;
```

- [ ] **Step 2: Write the pgTAP test**

```sql
-- supabase/tests/league_data_layer.sql
begin;
select plan(20);

-- `supabase db reset` seeds only public.seasons, so the row-level assertions below need
-- a member and a team of their own. These two statements assert nothing.
insert into public.members (display_name) values ('pgTAP Member')
  on conflict (display_name) do nothing;
insert into public.teams
  (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.members where display_name = 'pgTAP Member'),
  'pgtap-user', 999, 'pgTAP Team'
)
on conflict (season_id, sleeper_roster_id) do nothing;

select has_table('public', 'roster_holdings', 'roster_holdings table exists');
select has_table('public', 'team_season_state', 'team_season_state table exists');
select has_table('public', 'final_rosters', 'final_rosters table exists');
select has_table('public', 'player_projections', 'player_projections table exists');
select has_table('public', 'team_week_projections', 'team_week_projections table exists');
select has_table('public', 'nfl_state', 'nfl_state table exists');

select has_column('public', 'seasons', 'scoring_settings', 'seasons caches scoring_settings');
select has_column('public', 'seasons', 'waiver_budget', 'seasons caches waiver_budget');
select has_column(
  'public', 'members', 'sleeper_display_name',
  'members carries the Sleeper display name consumers fall back to'
);
select has_column('public', 'members', 'nickname', 'members carries the public nickname');

select policies_are(
  'public', 'team_week_projections',
  array['Public team_week_projections are readable', 'Automation writes team_week_projections']
);
select policies_are(
  'public', 'final_rosters',
  array['Public final_rosters are readable', 'Automation writes final_rosters']
);

-- roster_holdings is the one public table automation_worker may delete from.
select isnt_empty(
  $$select 1 from information_schema.role_table_grants
     where grantee = 'automation_worker' and table_schema = 'public'
       and table_name = 'roster_holdings' and privilege_type = 'DELETE'$$,
  'automation_worker holds DELETE on public.roster_holdings'
);

-- final_rosters is included in what this must not find: a snapshot is permanent.
select is_empty(
  $$select table_name from information_schema.role_table_grants
     where grantee = 'automation_worker' and table_schema = 'public'
       and privilege_type = 'DELETE' and table_name <> 'roster_holdings'$$,
  'automation_worker holds DELETE on no other public table'
);

-- The five board tables are published to Realtime; player_projections is not.
select bag_eq(
  $$select tablename::text from pg_publication_tables
     where pubname = 'supabase_realtime' and schemaname = 'public'$$,
  $$values ('roster_holdings'), ('team_season_state'), ('final_rosters'),
           ('team_week_projections'), ('nfl_state')$$,
  'exactly the five board tables are published to supabase_realtime'
);

select is(
  (select relreplident from pg_class where oid = 'public.roster_holdings'::regclass),
  'f'::"char",
  'roster_holdings uses replica identity full so deletes carry the old row'
);

-- faab_remaining is generated, not writable.
insert into public.team_season_state
  (season_id, team_id, faab_budget, faab_used, synced_at)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.teams where sleeper_roster_id = 999),
  1000, 250, now()
);
select is(
  (select faab_remaining from public.team_season_state order by id desc limit 1),
  750,
  'faab_remaining is generated from budget minus used'
);

-- nfl_state can only ever hold one row.
select throws_ok(
  $$insert into public.nfl_state (id, season, season_type, week, raw, synced_at)
    values (2, 2026, 'regular', 1, '{}'::jsonb, now())$$,
  '23514'::char(5),
  null,
  'nfl_state rejects any id but 1'
);

-- A team gets exactly one final roster, forever. The unique constraint is what makes
-- `on conflict do nothing` a permanent snapshot rather than a race.
select col_is_unique(
  'public', 'final_rosters', array['season_id', 'team_id'],
  'one final roster per team per season'
);

insert into public.final_rosters
  (season_id, team_id, eliminated_week, holdings, frozen_at)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.teams where sleeper_roster_id = 999),
  3, '[]'::jsonb, now()
);
select throws_ok(
  $$insert into public.final_rosters
      (season_id, team_id, eliminated_week, holdings, frozen_at)
    values (
      (select id from public.seasons where year = 2026),
      (select id from public.teams where sleeper_roster_id = 999),
      4, '[]'::jsonb, now()
    )$$,
  '23505'::char(5),
  null,
  'a second final roster for the same team is rejected'
);

select * from finish();
rollback;
```

`col_is_unique` reads the constraint, and the `throws_ok` right after it proves the
constraint actually fires — the freeze in Task 7 leans on both, so both are asserted.

- [ ] **Step 3: Run the migration and the tests**

Run: `supabase db reset && supabase test db`

Expected: `league_data_layer.sql .. ok`, 20 of 20 passing, and the three existing pgTAP
files still green.

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations supabase/tests/league_data_layer.sql
git commit -m "feat: add league data layer tables, final rosters, owner labels, and pgTAP"
```

### Task 3: The scoring dot product

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/scoring.py`
- Create: `packages/league-automation/tests/sleeper/test_scoring.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. Pure functions over two dicts.
- Produces:
  - `SCORING_DENYLIST: frozenset[str]` — Sleeper's convenience and draft-metadata fields, excluded from the product whatever the settings say.
  - `score_stat_line(stat_line: dict[str, object], scoring_settings: dict[str, object]) -> Decimal | None` — the dot product over keys present in both maps, rounded half-up to two decimals; `None` when no key could be scored.
  - `scoring_version(scoring_settings: dict[str, object]) -> str` — first 12 hex characters of SHA-256 over the canonicalized settings.
  - `preset_drift(league_points: Decimal | None, stat_line: dict[str, object]) -> Decimal | None` — absolute distance from the nearest of Sleeper's own `pts_ppr` / `pts_half_ppr` / `pts_std`, or `None` when either side is missing.
  - `DRIFT_POINTS = Decimal("3")`, `DRIFT_SHARE = Decimal("0.02")`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/sleeper/test_scoring.py
from decimal import Decimal

from ultimate_guillotine.sleeper.scoring import (
    SCORING_DENYLIST,
    preset_drift,
    score_stat_line,
    scoring_version,
)

# A deliberately tiny league so every expected number is hand-computable.
SETTINGS = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "fum_lost": -2.0,
    "bonus_rec_te": 0.5,
    "pts_ppr": 1.0,  # present in settings but never scorable: it is a preset, not a stat
}


def test_dot_product_matches_a_hand_computed_line() -> None:
    # 243.94 * 0.04 = 9.7576; 1.71 * 4 = 6.84; 0.9 * -1 = -0.9; 0.19 * -2 = -0.38
    # total 15.3176 -> 15.32
    line = {"pass_yd": 243.94, "pass_td": 1.71, "pass_int": 0.9, "fum_lost": 0.19,
            "gp": 1.0, "pts_ppr": 17.11}
    assert score_stat_line(line, SETTINGS) == Decimal("15.32")


def test_bonuses_and_negatives_both_land_in_the_product() -> None:
    # 5.1 * 1 + 62.78 * 0.1 + 0.46 * 6 + 5.1 * 0.5 = 5.1 + 6.278 + 2.76 + 2.55 = 16.688
    line = {"rec": 5.1, "rec_yd": 62.78, "rec_td": 0.46, "bonus_rec_te": 5.1}
    assert score_stat_line(line, SETTINGS) == Decimal("16.69")


def test_rounding_is_half_up_not_bankers() -> None:
    # 0.125 * 1 = 0.125 -> 0.13, and 0.135 -> 0.14. Python's round() gives 0.12 and 0.14.
    assert score_stat_line({"rec": 0.125}, {"rec": 1.0}) == Decimal("0.13")
    assert score_stat_line({"rec": 0.135}, {"rec": 1.0}) == Decimal("0.14")


def test_presets_and_denylisted_keys_never_enter_the_product() -> None:
    assert "pts_ppr" in SCORING_DENYLIST and "gp" in SCORING_DENYLIST
    assert "adp_dd_ppr" in SCORING_DENYLIST and "pos_adp_dd_ppr" in SCORING_DENYLIST
    # pts_ppr carries a scoring value in SETTINGS and still contributes nothing.
    assert score_stat_line({"rec": 2.0, "pts_ppr": 99.0}, SETTINGS) == Decimal("2.00")


def test_unscorable_line_is_none_not_zero() -> None:
    idp_only = {"idp_tkl": 2.98, "idp_int": 0.11, "gp": 1.0, "pts_ppr": 0.22}
    assert score_stat_line(idp_only, SETTINGS) is None


def test_a_line_of_scorable_zeros_is_zero_not_none() -> None:
    assert score_stat_line({"rec": 0.0}, SETTINGS) == Decimal("0.00")


def test_non_numeric_and_boolean_values_are_skipped() -> None:
    assert score_stat_line({"rec": "3", "rec_td": None, "pass_td": True}, SETTINGS) is None
    assert score_stat_line({"rec": "3", "rec_yd": 10.0}, SETTINGS) == Decimal("1.00")


def test_scoring_version_is_twelve_hex_chars_stable_and_order_independent() -> None:
    version = scoring_version(SETTINGS)
    assert len(version) == 12 and all(c in "0123456789abcdef" for c in version)
    assert version == scoring_version(dict(reversed(list(SETTINGS.items()))))
    assert version != scoring_version({**SETTINGS, "rec": 0.5})


def test_preset_drift_measures_distance_to_the_nearest_preset() -> None:
    line = {"pts_ppr": 19.69, "pts_half_ppr": 16.28, "pts_std": 12.86}
    assert preset_drift(Decimal("16.00"), line) == Decimal("0.28")
    assert preset_drift(None, line) is None
    assert preset_drift(Decimal("16.00"), {"gp": 1.0}) is None
```

- [ ] **Step 2: Run the tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_scoring.py -v`

Expected: FAIL, `ModuleNotFoundError: No module named 'ultimate_guillotine.sleeper.scoring'`.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/sleeper/scoring.py
"""League scoring as a pure dot product over Sleeper's stat keys.

Sleeper uses the same keys in a projection's ``stats`` map and in a league's
``scoring_settings``, so multiplying the two maps key-by-key and summing is
exactly the league's scoring rule -- bonuses and negatives included -- with no
per-format special cases. Nothing here touches the network or the database.
"""

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

#: Sleeper's own convenience totals and draft metadata. They are numbers that share the
#: namespace with real stats but are not stats: scoring them would double-count (the
#: presets) or invent points out of an average draft position.
SCORING_DENYLIST = frozenset({
    "pts_ppr",
    "pts_half_ppr",
    "pts_std",
    "gp",
    "gms_active",
    "adp_dd_ppr",
    "pos_adp_dd_ppr",
    "cmp_pct",
})

_PRESET_KEYS = ("pts_ppr", "pts_half_ppr", "pts_std")
_CENTS = Decimal("0.01")

#: A run posts one drift note when more than DRIFT_SHARE of scored players sit further
#: than DRIFT_POINTS from the nearest Sleeper preset.
DRIFT_POINTS = Decimal("3")
DRIFT_SHARE = Decimal("0.02")


def _number(value: object) -> Decimal | None:
    """Return ``value`` as a Decimal, or None when it is not a plain number.

    ``bool`` is excluded explicitly: it is a subclass of ``int`` and a True in a
    stat map is a flag someone added, not one point.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value))


def score_stat_line(
    stat_line: dict[str, object], scoring_settings: dict[str, object]
) -> Decimal | None:
    """Dot-product ``stat_line`` with ``scoring_settings``, rounded half-up to cents.

    Returns ``None`` when not one key could be scored: that is a missing
    projection, and a missing projection is never a zero.
    """
    total = Decimal(0)
    scored = 0
    for key, raw in stat_line.items():
        if key in SCORING_DENYLIST:
            continue
        stat = _number(raw)
        weight = _number(scoring_settings.get(key))
        if stat is None or weight is None:
            continue
        total += stat * weight
        scored += 1
    if scored == 0:
        return None
    return total.quantize(_CENTS, rounding=ROUND_HALF_UP)


def scoring_version(scoring_settings: dict[str, object]) -> str:
    """A short, stable fingerprint of the league's scoring rules.

    Keys are sorted and values coerced to float so a settings blob that Sleeper
    re-serializes differently still fingerprints the same.
    """
    canonical = {}
    for key in sorted(scoring_settings):
        value = _number(scoring_settings[key])
        if value is not None:
            canonical[key] = float(value)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:12]


def preset_drift(
    league_points: Decimal | None, stat_line: dict[str, object]
) -> Decimal | None:
    """Distance from ``league_points`` to the nearest Sleeper preset in ``stat_line``.

    A large drift across many players means the stat keys stopped lining up with
    the scoring keys, which is the one failure mode the dot product cannot see.
    """
    if league_points is None:
        return None
    presets = [p for p in (_number(stat_line.get(k)) for k in _PRESET_KEYS) if p is not None]
    if not presets:
        return None
    return min(abs(league_points - preset) for preset in presets)
```

- [ ] **Step 4: Run green, lint, commit**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_scoring.py -v && pnpm lint:agents`

Expected: 9 passed.

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/scoring.py \
        packages/league-automation/tests/sleeper/test_scoring.py
git commit -m "feat: score Sleeper stat lines against cached league scoring settings"
```

### Task 4: Roster payload model, slot classification, and team state

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/roster_state.py`
- Modify: `packages/league-automation/tests/fixtures/sleeper/rosters_2026.json`
- Create: `packages/league-automation/tests/sleeper/test_roster_state.py`

**Interfaces:**
- Consumes: `SleeperRoster`.
- Produces:
  - `SleeperRoster` gains `starters: list[str] = []`, `reserve: list[str] = []`, `taxi: list[str] = []`, `settings: dict[str, object] = {}`, `metadata: dict[str, object] = {}`. `starters`, `reserve`, and `taxi` reuse the existing null-to-empty-list validator; `settings` and `metadata` get a null-to-empty-**dict** validator.
  - `EMPTY_SLOT = "0"`.
  - `@dataclass(frozen=True) class Holding: sleeper_player_id: str; slot: str; slot_index: int | None; lineup_position: str | None`.
  - `@dataclass(frozen=True) class RosterClassification: holdings: tuple[Holding, ...]; starter_slots: int; empty_slots: int`.
  - `classify_holdings(roster: SleeperRoster, roster_positions: list[str]) -> RosterClassification`.
  - `@dataclass(frozen=True) class TeamState: faab_budget: int; faab_used: int; wins: int; losses: int; ties: int; points_for: Decimal; points_against: Decimal`.
  - `team_state_from_roster(roster: SleeperRoster, waiver_budget: int | None) -> TeamState`.
  - `@dataclass(frozen=True) class Elimination: is_eliminated: bool; eliminated_week: int | None; source: str | None` with `Elimination.none()`.
  - `infer_elimination(roster: SleeperRoster, week: int | None) -> Elimination`.
  - `merge_elimination(stored: Elimination | None, incoming: Elimination) -> Elimination`.
  - `bumps_state_version(stored: Elimination | None, merged: Elimination) -> bool`.

- [ ] **Step 1: Extend the roster fixture**

Replace `packages/league-automation/tests/fixtures/sleeper/rosters_2026.json`'s first two
entries with these, leaving the remaining sixteen as they are (they keep the old
`roster_id` / `owner_id` / `players` / `settings` shape, which still validates):

```json
[
  {
    "roster_id": 1,
    "owner_id": "user-01",
    "starters": ["4034", "6794", "0", "9488", "12517", "0", "7611", "12713", "SEA"],
    "players": ["4034", "6794", "9488", "12517", "7611", "12713", "SEA", "4943", "10881"],
    "reserve": ["10881"],
    "taxi": ["4943"],
    "settings": {
      "wins": 2, "losses": 1, "ties": 0,
      "fpts": 312, "fpts_decimal": 45,
      "fpts_against": 289, "fpts_against_decimal": 7,
      "waiver_budget_used": 250
    },
    "metadata": {}
  },
  {
    "roster_id": 2,
    "owner_id": "user-02",
    "starters": null,
    "players": null,
    "reserve": null,
    "taxi": null,
    "settings": {"wins": 0, "losses": 3, "ties": 0},
    "metadata": {"eliminated": "true"}
  }
]
```

- [ ] **Step 2: Write the failing tests**

```python
# packages/league-automation/tests/sleeper/test_roster_state.py
import json
from decimal import Decimal
from pathlib import Path

from ultimate_guillotine.sleeper.models import SleeperRoster
from ultimate_guillotine.sleeper.roster_state import (
    Elimination,
    bumps_state_version,
    classify_holdings,
    infer_elimination,
    merge_elimination,
    team_state_from_roster,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "rosters_2026.json"
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def rosters() -> list[SleeperRoster]:
    return [SleeperRoster.model_validate(r) for r in json.loads(FIXTURE.read_text())]


def test_slots_come_straight_from_the_sleeper_payload() -> None:
    result = classify_holdings(rosters()[0], POSITIONS)
    by_id = {h.sleeper_player_id: h for h in result.holdings}
    assert by_id["4034"].slot == "starter"
    assert by_id["10881"].slot == "ir"
    assert by_id["4943"].slot == "taxi"
    # In players but in no starters/reserve/taxi list, so it is bench.
    assert by_id["6794"].slot == "starter"
    assert {h.slot for h in result.holdings} == {"starter", "ir", "taxi"}


def test_starter_index_and_lineup_position_come_from_roster_positions() -> None:
    by_id = {h.sleeper_player_id: h for h in classify_holdings(rosters()[0], POSITIONS).holdings}
    assert (by_id["4034"].slot_index, by_id["4034"].lineup_position) == (0, "QB")
    assert (by_id["9488"].slot_index, by_id["9488"].lineup_position) == (3, "WR")
    assert (by_id["SEA"].slot_index, by_id["SEA"].lineup_position) == (8, "DEF")
    assert by_id["10881"].slot_index is None and by_id["10881"].lineup_position is None


def test_zero_starter_slots_produce_no_row_only_a_count() -> None:
    result = classify_holdings(rosters()[0], POSITIONS)
    assert "0" not in {h.sleeper_player_id for h in result.holdings}
    assert result.starter_slots == 9
    assert result.empty_slots == 2


def test_a_bench_only_roster_classifies_everything_bench() -> None:
    roster = SleeperRoster.model_validate(
        {"roster_id": 3, "owner_id": "u3", "players": ["a", "b"], "starters": []}
    )
    result = classify_holdings(roster, POSITIONS)
    assert [h.slot for h in result.holdings] == ["bench", "bench"]
    assert result.starter_slots == 0 and result.empty_slots == 0


def test_null_lists_and_dicts_become_empty() -> None:
    roster = rosters()[1]
    assert roster.starters == [] and roster.players == []
    assert roster.reserve == [] and roster.taxi == []
    assert classify_holdings(roster, POSITIONS).holdings == ()


def test_faab_and_points_recombine_sleepers_split_integers() -> None:
    state = team_state_from_roster(rosters()[0], waiver_budget=1000)
    assert (state.faab_budget, state.faab_used) == (1000, 250)
    assert state.points_for == Decimal("312.45")
    assert state.points_against == Decimal("289.07")
    assert (state.wins, state.losses, state.ties) == (2, 1, 0)


def test_a_league_without_a_waiver_budget_records_zero_not_none() -> None:
    state = team_state_from_roster(rosters()[1], waiver_budget=None)
    assert (state.faab_budget, state.faab_used) == (0, 0)
    assert state.points_for == Decimal("0") and state.points_against == Decimal("0")


def test_inference_reads_only_bens_metadata_tag() -> None:
    assert infer_elimination(rosters()[0], week=3) == Elimination.none()
    inferred = infer_elimination(rosters()[1], week=3)
    assert inferred == Elimination(True, 3, "sleeper_inferred")


def test_inferred_never_overwrites_adjudicated() -> None:
    ruled = Elimination(True, 2, "adjudicator")
    assert merge_elimination(ruled, Elimination(False, None, "sleeper_inferred")) == ruled
    assert merge_elimination(ruled, Elimination(True, 5, "sleeper_inferred")) == ruled
    # Manual outranks inference too, and the Adjudicator outranks everything.
    manual = Elimination(True, 4, "manual")
    assert merge_elimination(manual, Elimination(True, 6, "sleeper_inferred")) == manual
    assert merge_elimination(manual, ruled) == ruled
    assert merge_elimination(None, Elimination(True, 3, "sleeper_inferred")).is_eliminated


def test_state_version_bumps_only_on_an_actual_elimination_change() -> None:
    stored = Elimination(False, None, None)
    assert not bumps_state_version(stored, Elimination(False, None, "sleeper_inferred"))
    assert bumps_state_version(stored, Elimination(True, 3, "sleeper_inferred"))
    assert bumps_state_version(Elimination(True, 3, "adjudicator"),
                               Elimination(True, 4, "adjudicator"))
    assert not bumps_state_version(None, Elimination(True, 3, "adjudicator"))
```

- [ ] **Step 3: Run the tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_roster_state.py -v`

Expected: FAIL, `ModuleNotFoundError: No module named 'ultimate_guillotine.sleeper.roster_state'`.

- [ ] **Step 4: Extend `SleeperRoster`**

Replace the `SleeperRoster` class in `sleeper/models.py` with:

```python
class SleeperRoster(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    roster_id: int
    owner_id: str
    players: list[str] = []
    starters: list[str] = []
    reserve: list[str] = []
    taxi: list[str] = []
    settings: dict[str, object] = {}
    metadata: dict[str, object] = {}

    @field_validator("players", "starters", "reserve", "taxi", mode="before")
    @classmethod
    def _no_players_is_an_empty_roster(cls, value: object) -> object:
        """Sleeper sends ``null`` for an empty list, not ``[]``."""
        return [] if value is None else value

    @field_validator("settings", "metadata", mode="before")
    @classmethod
    def _no_settings_is_an_empty_map(cls, value: object) -> object:
        """Sleeper sends ``null`` for an absent settings/metadata block, not ``{}``."""
        return {} if value is None else value
```

- [ ] **Step 5: Implement `roster_state.py`**

```python
# packages/league-automation/src/ultimate_guillotine/sleeper/roster_state.py
"""Pure derivations from one Sleeper roster payload.

Slot classification, FAAB and record recombination, and the elimination
precedence rule all live here as functions over plain values, so every rule the
spec states has a test that needs no database and no network.
"""

from dataclasses import dataclass
from decimal import Decimal

from ultimate_guillotine.sleeper.models import SleeperRoster

#: Sleeper writes the string "0" into a starter slot the manager left blank.
EMPTY_SLOT = "0"

#: Precedence, lowest to highest. An inferred elimination never overwrites a ruled one.
_SOURCE_RANK = {None: 0, "sleeper_inferred": 1, "manual": 2, "adjudicator": 3}


@dataclass(frozen=True)
class Holding:
    sleeper_player_id: str
    slot: str
    slot_index: int | None
    lineup_position: str | None


@dataclass(frozen=True)
class RosterClassification:
    holdings: tuple[Holding, ...]
    starter_slots: int
    empty_slots: int


def classify_holdings(
    roster: SleeperRoster, roster_positions: list[str]
) -> RosterClassification:
    """Split a roster into starter / ir / taxi / bench rows, as Sleeper reports them.

    An id in ``starters`` is a starter, in ``reserve`` is ``ir``, in ``taxi`` is
    ``taxi``, and anything else in ``players`` is bench. A blank starter slot
    produces no row at all, only a count -- there is nobody to record.
    """
    holdings: list[Holding] = []
    seen: set[str] = set()
    empty = 0
    for index, player_id in enumerate(roster.starters):
        if not player_id or player_id == EMPTY_SLOT:
            empty += 1
            continue
        position = roster_positions[index] if index < len(roster_positions) else None
        holdings.append(Holding(player_id, "starter", index, position))
        seen.add(player_id)
    for slot, ids in (("ir", roster.reserve), ("taxi", roster.taxi),
                      ("bench", roster.players)):
        for player_id in ids:
            if not player_id or player_id == EMPTY_SLOT or player_id in seen:
                continue
            holdings.append(Holding(player_id, slot, None, None))
            seen.add(player_id)
    return RosterClassification(tuple(holdings), len(roster.starters), empty)


@dataclass(frozen=True)
class TeamState:
    faab_budget: int
    faab_used: int
    wins: int
    losses: int
    ties: int
    points_for: Decimal
    points_against: Decimal


def _int(settings: dict[str, object], key: str) -> int:
    value = settings.get(key)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _recombine(settings: dict[str, object], whole_key: str, decimal_key: str) -> Decimal:
    """Sleeper splits fantasy points into two integers; put them back together."""
    whole = Decimal(_int(settings, whole_key))
    hundredths = Decimal(_int(settings, decimal_key))
    return whole + hundredths / Decimal(100)


def team_state_from_roster(roster: SleeperRoster, waiver_budget: int | None) -> TeamState:
    """Record, points, and FAAB for one team, from the roster's settings block."""
    settings = roster.settings
    return TeamState(
        faab_budget=int(waiver_budget or 0),
        faab_used=_int(settings, "waiver_budget_used"),
        wins=_int(settings, "wins"),
        losses=_int(settings, "losses"),
        ties=_int(settings, "ties"),
        points_for=_recombine(settings, "fpts", "fpts_decimal"),
        points_against=_recombine(settings, "fpts_against", "fpts_against_decimal"),
    )


@dataclass(frozen=True)
class Elimination:
    is_eliminated: bool
    eliminated_week: int | None
    source: str | None

    @classmethod
    def none(cls) -> "Elimination":
        return cls(False, None, None)


def infer_elimination(roster: SleeperRoster, week: int | None) -> Elimination:
    """Provisional elimination from a Sleeper roster tag Ben sets by hand.

    Deliberately narrow: only an explicit ``metadata.eliminated`` tag counts.
    Absence from ``get_matchups`` is not read as elimination, because whether an
    eliminated roster stays in Sleeper is still an open question for Ben, and a
    wrong guess would silently eliminate live teams.
    """
    tag = roster.metadata.get("eliminated")
    tagged = tag is True or (isinstance(tag, str) and tag.strip().lower() in {"true", "1", "yes"})
    if not tagged:
        return Elimination.none()
    return Elimination(True, week, "sleeper_inferred")


def merge_elimination(stored: Elimination | None, incoming: Elimination) -> Elimination:
    """Keep the higher-ranked source. The Weekly Adjudicator is authoritative."""
    if stored is None:
        return incoming
    if _SOURCE_RANK[incoming.source] >= _SOURCE_RANK[stored.source]:
        return incoming
    return stored


def bumps_state_version(stored: Elimination | None, merged: Elimination) -> bool:
    """Did the elimination fact itself change? A new source alone does not count."""
    if stored is None:
        return False
    return (stored.is_eliminated, stored.eliminated_week) != (
        merged.is_eliminated,
        merged.eliminated_week,
    )
```

- [ ] **Step 6: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

Expected: the new file's 10 tests pass and the existing `tests/sleeper/test_sync.py`
still passes (the new roster fields all default).

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/models.py \
        packages/league-automation/src/ultimate_guillotine/sleeper/roster_state.py \
        packages/league-automation/tests/sleeper/test_roster_state.py \
        packages/league-automation/tests/fixtures/sleeper/rosters_2026.json
git commit -m "feat: classify roster slots and derive team season state from Sleeper"
```

### Task 5: `public.nfl_state` and the week every job reads

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/state.py`
- Create: `packages/league-automation/tests/sleeper/test_state.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`

**Interfaces:**
- Consumes: `SleeperClient.get_nfl_state`, the `conn` fixture, `run_scheduled`.
- Produces:
  - `@dataclass(frozen=True) class NflState: season: int; season_type: str; week: int; display_week: int | None; leg: int | None; previous_season: int | None; season_start_date: date | None; raw: dict[str, object]; synced_at: datetime`.
  - `parse_nfl_state(raw: dict[str, object], now: datetime) -> NflState` — coerces Sleeper's string `season` / `previous_season` to ints and its `season_start_date` to a `date`; raises `ValueError` on a payload with no usable `season` or `week`.
  - `NflStateRepository(conn)` with `.upsert(state: NflState) -> None` and `.get() -> NflState | None`.
  - `STATE_MAX_AGE = timedelta(minutes=60)`.
  - `sync_nfl_state(client, conn, now: datetime) -> NflState` — fetch, parse, upsert in one transaction.
  - `current_week(client, conn, now: datetime) -> NflState` — returns the stored row when it is fresher than `STATE_MAX_AGE`, otherwise refreshes inline first.
  - `ug sleeper state [--quiet]` recording agent `nfl-state`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/sleeper/test_state.py
from datetime import UTC, date, datetime, timedelta

import pytest

from ultimate_guillotine.sleeper.state import (
    NflStateRepository,
    current_week,
    parse_nfl_state,
    sync_nfl_state,
)

# Recorded from GET https://api.sleeper.app/v1/state/nfl on 2026-09-09.
RAW = {
    "week": 1, "leg": 1, "season_type": "regular", "season": "2026",
    "league_season": "2026", "previous_season": "2025",
    "season_start_date": "2026-09-09", "display_week": 1,
    "league_create_season": "2026", "season_has_scores": True,
}
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class FakeStateClient:
    def __init__(self, raw: dict, week: int | None = None) -> None:
        self.raw = {**raw, **({"week": week} if week is not None else {})}
        self.calls = 0

    def get_nfl_state(self) -> dict:
        self.calls += 1
        return self.raw


def test_parse_coerces_sleepers_string_season_and_date() -> None:
    state = parse_nfl_state(RAW, NOW)
    assert state.season == 2026 and state.previous_season == 2025
    assert state.week == 1 and state.display_week == 1 and state.leg == 1
    assert state.season_type == "regular"
    assert state.season_start_date == date(2026, 9, 9)
    assert state.raw["league_season"] == "2026"
    assert state.synced_at == NOW


def test_parse_rejects_a_payload_without_a_week() -> None:
    with pytest.raises(ValueError, match="week"):
        parse_nfl_state({"season": "2026", "season_type": "regular"}, NOW)


def test_sync_upserts_one_row_and_repeats_identically(conn) -> None:
    client = FakeStateClient(RAW)
    first = sync_nfl_state(client, conn, NOW)
    second = sync_nfl_state(client, conn, NOW)
    assert first == second
    with conn.cursor() as cur:
        cur.execute("select count(*), max(id) from public.nfl_state")
        assert cur.fetchone() == (1, 1)
    assert NflStateRepository(conn).get() == first


def test_current_week_reuses_a_fresh_row_without_calling_sleeper(conn) -> None:
    client = FakeStateClient(RAW)
    sync_nfl_state(client, conn, NOW)
    client.calls = 0
    state = current_week(client, conn, NOW + timedelta(minutes=30))
    assert state.week == 1 and client.calls == 0


def test_current_week_refreshes_a_stale_row_inline(conn) -> None:
    sync_nfl_state(FakeStateClient(RAW), conn, NOW)
    fresh = FakeStateClient(RAW, week=2)
    state = current_week(fresh, conn, NOW + timedelta(minutes=61))
    assert state.week == 2 and fresh.calls == 1
    assert NflStateRepository(conn).get().week == 2


def test_current_week_fetches_when_there_is_no_row_at_all(conn) -> None:
    client = FakeStateClient(RAW)
    assert current_week(client, conn, NOW).week == 1
    assert client.calls == 1
```

- [ ] **Step 2: Run the tests red**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_state.py -v`

Expected: FAIL, `ModuleNotFoundError: No module named 'ultimate_guillotine.sleeper.state'`.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/sleeper/state.py
"""The NFL week, as one row every week-scoped job reads instead of the clock.

Deriving a week from the calendar is wrong twice a season (bye structure, a
pushed game) and wrong silently. This module makes the week a fact with a
timestamp: fresh enough and it is reused, stale and the caller refreshes it
inline rather than proceeding on a pinned week.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient

#: Past this age the stored week is not trusted; a week-scoped job refreshes it first.
STATE_MAX_AGE = timedelta(minutes=60)


@dataclass(frozen=True)
class NflState:
    season: int
    season_type: str
    week: int
    display_week: int | None
    leg: int | None
    previous_season: int | None
    season_start_date: date | None
    raw: dict[str, object]
    synced_at: datetime


def _int_or_none(value: object) -> int | None:
    """Sleeper answers with ``"2026"``, not ``2026``, for every season field."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _date_or_none(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_nfl_state(raw: dict[str, object], now: datetime) -> NflState:
    """Turn Sleeper's state payload into typed values, or refuse it."""
    season = _int_or_none(raw.get("season"))
    week = _int_or_none(raw.get("week"))
    season_type = raw.get("season_type")
    if season is None:
        raise ValueError("sleeper state payload has no season")
    if week is None:
        raise ValueError("sleeper state payload has no week")
    if not isinstance(season_type, str) or not season_type:
        raise ValueError("sleeper state payload has no season_type")
    return NflState(
        season=season,
        season_type=season_type,
        week=week,
        display_week=_int_or_none(raw.get("display_week")),
        leg=_int_or_none(raw.get("leg")),
        previous_season=_int_or_none(raw.get("previous_season")),
        season_start_date=_date_or_none(raw.get("season_start_date")),
        raw=dict(raw),
        synced_at=now,
    )


class NflStateRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert(self, state: NflState) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.nfl_state
                  (id, season, season_type, week, display_week, leg, previous_season,
                   season_start_date, raw, synced_at)
                values (1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do update set
                  season = excluded.season, season_type = excluded.season_type,
                  week = excluded.week, display_week = excluded.display_week,
                  leg = excluded.leg, previous_season = excluded.previous_season,
                  season_start_date = excluded.season_start_date, raw = excluded.raw,
                  synced_at = excluded.synced_at
                """,
                (
                    state.season, state.season_type, state.week, state.display_week,
                    state.leg, state.previous_season, state.season_start_date,
                    json.dumps(state.raw), state.synced_at,
                ),
            )

    def get(self) -> NflState | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select season, season_type, week, display_week, leg, previous_season,
                       season_start_date, raw, synced_at
                from public.nfl_state where id = 1
                """
            )
            row = cur.fetchone()
        return NflState(*row) if row else None


def sync_nfl_state(client: SleeperClient, conn: psycopg.Connection, now: datetime) -> NflState:
    """Refresh the single state row. Fetch first, then one short transaction."""
    state = parse_nfl_state(client.get_nfl_state(), now)
    with conn.transaction():
        NflStateRepository(conn).upsert(state)
    return state


def current_week(
    client: SleeperClient, conn: psycopg.Connection, now: datetime
) -> NflState:
    """The week to work on: the stored row when fresh, a fresh fetch otherwise.

    A stalled state job must never silently pin the league to last week, so
    staleness costs one extra Sleeper call rather than correctness.
    """
    stored = NflStateRepository(conn).get()
    if stored is not None and now - stored.synced_at <= STATE_MAX_AGE:
        return stored
    return sync_nfl_state(client, conn, now)
```

- [ ] **Step 4: Add the CLI command**

In `cli/sleeper.py`, add the import `from ultimate_guillotine.sleeper.state import sync_nfl_state`,
register the subparser inside `register` (after the `players` parser):

```python
    state_parser = sleeper_sub.add_parser("state", help="refresh the NFL week row")
    state_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    state_parser.set_defaults(handler=cmd_state)
```

and the handler:

```python
def cmd_state(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        state = sync_nfl_state(SleeperClient(httpx.Client()), conn, now)
        if not args.quiet:
            print(f"nfl state: {state.season} {state.season_type} week {state.week}")
        return 0

    return run_scheduled(conn, "nfl-state", now, action)
```

- [ ] **Step 5: Run green, lint, commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres pnpm test:agents && pnpm lint:agents`

Expected: the six state tests pass.

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/state.py \
        packages/league-automation/src/ultimate_guillotine/cli/sleeper.py \
        packages/league-automation/tests/sleeper/test_state.py
git commit -m "feat: record the NFL week in public.nfl_state and add ug sleeper state"
```

### Task 6: Extend `sync_season` with settings, holdings, team state, and owner labels

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/sync.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/roster_state.py` (add the two repositories)
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/models.py` (`SleeperLeague` gains the settings fields)
- Modify: `packages/league-automation/tests/fixtures/sleeper/league_2026.json`
- Create: `packages/league-automation/tests/sleeper/test_sync_league_data.py`

**Interfaces:**
- Consumes: `classify_holdings`, `team_state_from_roster`, `infer_elimination`, `merge_elimination`, `bumps_state_version`, `Elimination`, `current_week`.
- Produces:
  - `SleeperLeague` gains `scoring_settings: dict[str, object] = {}`, `roster_positions: list[str] = []`, `settings: dict[str, object] = {}`, and a property `waiver_budget: int | None` reading `settings["waiver_budget"]`.
  - `SleeperUser` gains `username: str = ""` and a property `sleeper_display_name: str` returning `display_name`, or `username` when Sleeper left the display name blank.
  - `SyncReport` gains `holdings: int` and `states: int` (keeping `members` and `teams`).
  - `SeasonSettingsRepository(conn).cache(season_id, league, now) -> None` writing `scoring_settings`, `roster_positions`, `waiver_budget`, `league_synced_at`.
  - `RosterHoldingRepository(conn).replace_for_team(season_id, team_id, holdings, now) -> int` — upserts every holding then deletes that team's rows whose player id was not in the set; returns rows kept.
  - `TeamStateRepository(conn).get_elimination(season_id, team_id) -> Elimination | None` and `.upsert(season_id, team_id, state, elimination, now) -> None`.
  - `sync_season` writes `public.members.sleeper_display_name` on every member upsert and never touches `public.members.nickname`, which `ug members aliases load` owns (Task 12).
  - `sync_season(client, conn, year, league_id, week=None)` — the new `week` keyword is the week an inferred elimination is stamped with; `None` leaves `eliminated_week` null.

- [ ] **Step 1: Extend the league fixture**

Add these three keys to `packages/league-automation/tests/fixtures/sleeper/league_2026.json`
(a trimmed but real subset of the league's 128 scoring keys, read live on 2026-09-09):

```json
  "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"],
  "settings": {"waiver_budget": 1000},
  "scoring_settings": {
    "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -1.0, "pass_2pt": 2.0,
    "rush_yd": 0.1, "rush_td": 6.0, "rush_2pt": 2.0,
    "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rec_2pt": 2.0,
    "bonus_rec_te": 0.0, "bonus_rec_wr": 0.0, "bonus_rec_rb": 0.0,
    "fum_lost": -2.0, "fum_rec": 2.0, "def_td": 6.0, "int": 2.0, "sack": 1.0,
    "safe": 2.0, "ff": 1.0, "blk_kick": 2.0,
    "fgm_0_19": 3.0, "fgm_20_29": 3.0, "fgm_30_39": 3.0, "fgm_40_49": 4.0,
    "fgm_50p": 5.0, "xpm": 1.0,
    "pts_allow_0": 10.0, "pts_allow_1_6": 7.0, "pts_allow_7_13": 4.0,
    "pts_allow_14_20": 1.0, "pts_allow_21_27": 0.0, "pts_allow_28_34": -1.0,
    "pts_allow_35p": -4.0
  }
```

- [ ] **Step 2: Write the failing tests**

```python
# packages/league-automation/tests/sleeper/test_sync_league_data.py
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ultimate_guillotine.sleeper.models import SleeperLeague, SleeperRoster, SleeperUser
from ultimate_guillotine.sleeper.sync import sync_season

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sleeper"
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
LEAGUE_ID = "1389372259260452864"


class FakeClient:
    def __init__(self, rosters: list[dict]) -> None:
        self._league = SleeperLeague.model_validate(
            json.loads((FIXTURES / "league_2026.json").read_text())
        )
        self._users = [
            SleeperUser.model_validate(u)
            for u in json.loads((FIXTURES / "users_2026.json").read_text())
        ]
        self._rosters = [SleeperRoster.model_validate(r) for r in rosters]

    def get_league(self, league_id: str) -> SleeperLeague:
        return self._league

    def get_users(self, league_id: str) -> list[SleeperUser]:
        return self._users

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return self._rosters


def rosters() -> list[dict]:
    return json.loads((FIXTURES / "rosters_2026.json").read_text())


def season_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        return cur.fetchone()[0]


def team_id(conn, roster_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "select id from public.teams where season_id = %s and sleeper_roster_id = %s",
            (season_id(conn), roster_id),
        )
        return cur.fetchone()[0]


def test_sync_caches_the_leagues_scoring_settings_on_the_season(conn) -> None:
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select scoring_settings, roster_positions, waiver_budget, league_synced_at "
            "from public.seasons where year = 2026"
        )
        scoring, positions, budget, synced = cur.fetchone()
    assert scoring["rec"] == 1.0 and scoring["pass_yd"] == 0.04
    assert positions == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    assert budget == 1000 and synced is not None


def test_sync_writes_holdings_with_slots_and_lineup_positions(conn) -> None:
    report = sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    assert report.holdings > 0 and report.states == 18
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, slot, slot_index, lineup_position "
            "from public.roster_holdings where team_id = %s order by sleeper_player_id",
            (team_id(conn, 1),),
        )
        rows = dict((r[0], r[1:]) for r in cur.fetchall())
    assert rows["4034"] == ("starter", 0, "QB")
    assert rows["10881"] == ("ir", None, None)
    assert rows["4943"] == ("taxi", None, None)
    assert "0" not in rows


def test_a_dropped_player_disappears_from_holdings(conn) -> None:
    payload = rosters()
    sync_season(FakeClient(payload), conn, 2026, LEAGUE_ID, week=3)
    payload[0]["players"] = [p for p in payload[0]["players"] if p != "6794"]
    payload[0]["starters"] = ["4034", "0", "0", "9488", "12517", "0", "7611", "12713", "SEA"]
    sync_season(FakeClient(payload), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.roster_holdings "
            "where team_id = %s and sleeper_player_id = '6794'",
            (team_id(conn, 1),),
        )
        assert cur.fetchone()[0] == 0


def test_faab_record_and_points_land_in_team_season_state(conn) -> None:
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select faab_budget, faab_used, faab_remaining, wins, losses, points_for, "
            "points_against from public.team_season_state where team_id = %s",
            (team_id(conn, 1),),
        )
        row = cur.fetchone()
    assert row == (1000, 250, 750, 2, 1, Decimal("312.45"), Decimal("289.07"))


def test_an_adjudicated_elimination_survives_a_sync_that_infers_otherwise(conn) -> None:
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    ruled_team = team_id(conn, 1)
    with conn.cursor() as cur:
        cur.execute(
            "update public.team_season_state set is_eliminated = true, eliminated_week = 2,"
            " elimination_source = 'adjudicator', state_version = 2 where team_id = %s",
            (ruled_team,),
        )
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select is_eliminated, eliminated_week, elimination_source, state_version "
            "from public.team_season_state where team_id = %s",
            (ruled_team,),
        )
        assert cur.fetchone() == (True, 2, "adjudicator", 2)


def test_a_tagged_roster_is_recorded_as_provisionally_eliminated(conn) -> None:
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select is_eliminated, eliminated_week, elimination_source, state_version "
            "from public.team_season_state where team_id = %s",
            (team_id(conn, 2),),
        )
        assert cur.fetchone() == (True, 3, "sleeper_inferred", 1)


def test_sleeper_display_name_falls_back_to_the_username() -> None:
    """Sleeper occasionally returns an empty display_name, and then the username is
    the only label left. Whenever a display name exists it wins: the bare username is
    never what a consumer shows."""
    blank = SleeperUser(user_id="u", display_name="", username="ghostrider")
    assert blank.sleeper_display_name == "ghostrider"
    named = SleeperUser(user_id="u", display_name="Member01", username="member01_2019")
    assert named.sleeper_display_name == "Member01"


def test_sync_records_each_owners_sleeper_display_name(conn) -> None:
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_display_name, nickname from public.members "
            "where display_name = 'Member01'"
        )
        assert cur.fetchone() == ("Member01", None)


def test_sync_never_clears_a_loaded_nickname(conn) -> None:
    """`ug members aliases load` owns nickname. A sync refreshes the Sleeper label
    beside it and must leave the nickname exactly where it found it."""
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "update public.members set nickname = 'Big Ben' where display_name = 'Member01'"
        )
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select nickname, sleeper_display_name from public.members "
            "where display_name = 'Member01'"
        )
        assert cur.fetchone() == ("Big Ben", "Member01")


def test_repeated_syncs_produce_identical_rows(conn) -> None:
    client = FakeClient(rosters())
    sync_season(client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select season_id, team_id, sleeper_player_id, slot, slot_index, "
            "lineup_position from public.roster_holdings order by id"
        )
        first = cur.fetchall()
    sync_season(client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select season_id, team_id, sleeper_player_id, slot, slot_index, "
            "lineup_position from public.roster_holdings order by id"
        )
        assert cur.fetchall() == first
```

- [ ] **Step 3: Run the tests red**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_sync_league_data.py -v`

Expected: FAIL, `TypeError: sync_season() got an unexpected keyword argument 'week'`.

- [ ] **Step 4: Extend `SleeperLeague` and `SleeperUser`**

```python
class SleeperLeague(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    league_id: str
    name: str
    season: str
    total_rosters: int
    scoring_settings: dict[str, object] = {}
    roster_positions: list[str] = []
    settings: dict[str, object] = {}

    @property
    def waiver_budget(self) -> int | None:
        """The league's FAAB budget, or None when Sleeper is not running one."""
        value = self.settings.get("waiver_budget")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)
```

And add the username field and the label property to `SleeperUser`, leaving
`user_id`, `display_name`, `metadata`, and the `team_name` property exactly as they are:

```python
class SleeperUser(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    username: str = ""
    metadata: dict[str, object] = {}

    @property
    def team_name(self) -> str:
        """The user's configured team name, or their display name."""
        value = self.metadata.get("team_name")
        return value if isinstance(value, str) and value else self.display_name

    @property
    def sleeper_display_name(self) -> str:
        """The label a consumer falls back to when a member has no nickname.

        Sleeper's ``display_name``, or the ``username`` on the rare account that
        has none. Consumers never render the bare username otherwise, and never
        render ``members.display_name``, which is a matching key.
        """
        return self.display_name or self.username
```

- [ ] **Step 5: Add the repositories to `roster_state.py`**

```python
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.sleeper.models import SleeperLeague


class SeasonSettingsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def cache(self, season_id: int, league: SleeperLeague, now: datetime) -> None:
        """Cache the league's scoring rules on the season row, refreshed every sync."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update public.seasons
                set scoring_settings = %s, roster_positions = %s, waiver_budget = %s,
                    league_synced_at = %s
                where id = %s
                """,
                (
                    Jsonb(league.scoring_settings),
                    Jsonb(league.roster_positions),
                    league.waiver_budget,
                    now,
                    season_id,
                ),
            )


class RosterHoldingRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_for_team(
        self, season_id: int, team_id: int, holdings: tuple[Holding, ...], now: datetime
    ) -> int:
        """Upsert every holding, then delete the ones this team no longer has.

        The delete is what makes a dropped player vanish. It runs in the caller's
        transaction, alongside the upserts, so the board never sees a roster with
        both the old and the new player on it.
        """
        with self._conn.cursor() as cur:
            if holdings:
                cur.executemany(
                    """
                    insert into public.roster_holdings
                      (season_id, team_id, sleeper_player_id, slot, slot_index,
                       lineup_position, synced_at)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (season_id, team_id, sleeper_player_id) do update set
                      slot = excluded.slot, slot_index = excluded.slot_index,
                      lineup_position = excluded.lineup_position,
                      synced_at = excluded.synced_at
                    """,
                    [
                        (season_id, team_id, h.sleeper_player_id, h.slot, h.slot_index,
                         h.lineup_position, now)
                        for h in holdings
                    ],
                )
            cur.execute(
                """
                delete from public.roster_holdings
                where season_id = %s and team_id = %s
                  and not (sleeper_player_id = any(%s))
                """,
                (season_id, team_id, [h.sleeper_player_id for h in holdings]),
            )
        return len(holdings)


class TeamStateRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def get_elimination(self, season_id: int, team_id: int) -> Elimination | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "select is_eliminated, eliminated_week, elimination_source "
                "from public.team_season_state where season_id = %s and team_id = %s",
                (season_id, team_id),
            )
            row = cur.fetchone()
        return Elimination(*row) if row else None

    def upsert(
        self,
        season_id: int,
        team_id: int,
        state: TeamState,
        elimination: Elimination,
        now: datetime,
        bump_version: bool,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.team_season_state
                  (season_id, team_id, faab_budget, faab_used, wins, losses, ties,
                   points_for, points_against, is_eliminated, eliminated_week,
                   elimination_source, synced_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, team_id) do update set
                  faab_budget = excluded.faab_budget, faab_used = excluded.faab_used,
                  wins = excluded.wins, losses = excluded.losses, ties = excluded.ties,
                  points_for = excluded.points_for,
                  points_against = excluded.points_against,
                  is_eliminated = excluded.is_eliminated,
                  eliminated_week = excluded.eliminated_week,
                  elimination_source = excluded.elimination_source,
                  state_version = public.team_season_state.state_version + %s,
                  synced_at = excluded.synced_at
                """,
                (
                    season_id, team_id, state.faab_budget, state.faab_used, state.wins,
                    state.losses, state.ties, state.points_for, state.points_against,
                    elimination.is_eliminated, elimination.eliminated_week,
                    elimination.source, now, 1 if bump_version else 0,
                ),
            )
```

- [ ] **Step 6: Extend `sync_season`**

Change the dataclass and signature in `sleeper/sync.py`:

```python
@dataclass(frozen=True)
class SyncReport:
    members: int
    teams: int
    holdings: int
    states: int
```

Add the imports and, inside the existing `with conn.transaction(), conn.cursor() as cur:`
block, immediately after `validate_league(...)`:

```python
        SeasonSettingsRepository(conn).cache(season_id, league, now)
```

Replace the `insert into public.members` statement in the user loop with this one, which
refreshes the label beside the key. `nickname` is deliberately absent from both the column
list and the `do update set` clause: `ug members aliases load` owns it (Task 12), and a
sync that listed it would blank every nickname in the league every ten minutes.

```python
            cur.execute(
                """
                    insert into public.members (display_name, sleeper_display_name)
                    values (%s, %s)
                    on conflict (display_name) do update set
                        display_name = excluded.display_name,
                        sleeper_display_name = excluded.sleeper_display_name
                    returning id
                    """,
                (user.display_name, user.sleeper_display_name),
            )
```

and, inside the existing roster loop right after the `insert into public.teams` statement,
replace `teams_synced += 1` with:

```python
            cur.execute(
                "select id from public.teams where season_id = %s and sleeper_roster_id = %s",
                (season_id, roster.roster_id),
            )
            team_row = cur.fetchone()
            if team_row is None:
                raise RuntimeError("team upsert returned no id")
            team_id = team_row[0]

            classification = classify_holdings(roster, league.roster_positions)
            holdings_written += holdings_repo.replace_for_team(
                season_id, team_id, classification.holdings, now
            )

            stored = state_repo.get_elimination(season_id, team_id)
            merged = merge_elimination(stored, infer_elimination(roster, week))
            state_repo.upsert(
                season_id,
                team_id,
                team_state_from_roster(roster, league.waiver_budget),
                merged,
                now,
                bumps_state_version(stored, merged),
            )
            states_written += 1
            teams_synced += 1
```

with `now = datetime.now(UTC)` taken at the top of the function (before the fetch),
`holdings_written = 0`, `states_written = 0`, `holdings_repo = RosterHoldingRepository(conn)`,
and `state_repo = TeamStateRepository(conn)` initialised just before the loop. The signature
becomes:

```python
def sync_season(
    client: SleeperClient,
    conn: psycopg.Connection,
    year: int,
    league_id: str,
    week: int | None = None,
) -> SyncReport:
```

and the return becomes
`return SyncReport(len(member_ids), teams_synced, holdings_written, states_written)`.

- [ ] **Step 7: Feed the week in from the CLI**

In `cli/sleeper.py`'s `cmd_sync`, replace the body of `action` with:

```python
    def action(run_id: int) -> int:
        client = SleeperClient(httpx.Client())
        state = current_week(client, conn, now)
        report = sync_season(
            client, conn, SYNC_YEAR, deps.settings.sleeper_league_id, week=state.week
        )
        if not args.quiet:
            print(
                f"sleeper sync: {report.members} members, {report.teams} teams, "
                f"{report.holdings} holdings, {report.states} team states"
            )
        return 0
```

adding `from ultimate_guillotine.sleeper.state import current_week` to the imports.

- [ ] **Step 8: Run green, lint, commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres pnpm test:agents && pnpm lint:agents`

Expected: the ten new tests pass; the existing `tests/sleeper/test_sync.py` fake-connection
tests still pass (their fake cursor returns a row for every `select`, which the new team-id
lookup also uses).

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper \
        packages/league-automation/src/ultimate_guillotine/cli/sleeper.py \
        packages/league-automation/tests/sleeper packages/league-automation/tests/fixtures
git commit -m "feat: sync roster holdings, team state, league settings, and owner labels"
```

### Task 7: Freeze the final roster of an eliminated team

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/roster_state.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/sync.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`
- Create: `packages/league-automation/tests/sleeper/test_final_rosters.py`

**Interfaces:**
- Consumes: `public.final_rosters` (Task 2); `Holding`, `classify_holdings`, `Elimination`, `merge_elimination`, `infer_elimination` (Task 4); `sync_season`, `SyncReport`, `RosterHoldingRepository`, `TeamStateRepository` (Task 6).
- Produces:
  - `holdings_payload(holdings: tuple[Holding, ...]) -> list[dict[str, object]]` — the snapshot body, one dict per holding with keys `sleeper_player_id`, `slot`, `slot_index`, `lineup_position`, in classification order (starters by lineup index, then ir, taxi, bench).
  - `FinalRosterRepository(conn).freeze(season_id, team_id, eliminated_week, holdings, now) -> bool` — inserts one `public.final_rosters` row with `on conflict (season_id, team_id) do nothing`; returns `True` only when this call wrote the row.
  - `SyncReport` gains `frozen: int` (keeping `members`, `teams`, `holdings`, `states`).

**Why this lives in the sync.** The Weekly Adjudicator is the authoritative source of an
elimination, but it writes that ruling straight into `public.team_season_state` — it does
not call `sync_season`. So the freeze triggers on the first sync that *observes*
`merge_elimination` returning `is_eliminated = True`, whichever source produced it: the
Adjudicator's row already in the table, or the provisional Sleeper tag read this run. The
snapshot therefore lands within one sync cycle (10 minutes) of the ruling, `final_rosters`
has exactly one writer, and no trigger or second job is needed.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/sleeper/test_final_rosters.py
import json
from pathlib import Path

from ultimate_guillotine.sleeper.models import SleeperLeague, SleeperRoster, SleeperUser
from ultimate_guillotine.sleeper.roster_state import Holding, holdings_payload
from ultimate_guillotine.sleeper.sync import sync_season

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sleeper"
LEAGUE_ID = "1389372259260452864"


class FakeClient:
    def __init__(self, rosters: list[dict]) -> None:
        self._league = SleeperLeague.model_validate(
            json.loads((FIXTURES / "league_2026.json").read_text())
        )
        self._users = [
            SleeperUser.model_validate(u)
            for u in json.loads((FIXTURES / "users_2026.json").read_text())
        ]
        self._rosters = [SleeperRoster.model_validate(r) for r in rosters]

    def get_league(self, league_id: str) -> SleeperLeague:
        return self._league

    def get_users(self, league_id: str) -> list[SleeperUser]:
        return self._users

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return self._rosters


def rosters() -> list[dict]:
    return json.loads((FIXTURES / "rosters_2026.json").read_text())


def tagged_rosters() -> list[dict]:
    """Roster 1, the one with a full lineup, tagged the way Ben tags an out team."""
    payload = rosters()
    payload[0]["metadata"] = {"eliminated": "true"}
    return payload


def team_id(conn, roster_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "select t.id from public.teams t join public.seasons s on s.id = t.season_id "
            "where s.year = 2026 and t.sleeper_roster_id = %s",
            (roster_id,),
        )
        return cur.fetchone()[0]


def snapshot(conn, team: int):
    with conn.cursor() as cur:
        cur.execute(
            "select eliminated_week, holdings, frozen_at from public.final_rosters "
            "where team_id = %s",
            (team,),
        )
        return cur.fetchone()


def test_holdings_payload_keeps_classification_order_and_every_slot_field() -> None:
    holdings = (
        Holding("4034", "starter", 0, "QB"),
        Holding("10881", "ir", None, None),
    )
    assert holdings_payload(holdings) == [
        {"sleeper_player_id": "4034", "slot": "starter", "slot_index": 0,
         "lineup_position": "QB"},
        {"sleeper_player_id": "10881", "slot": "ir", "slot_index": None,
         "lineup_position": None},
    ]
    assert holdings_payload(()) == []


def test_an_elimination_freezes_that_teams_holdings(conn) -> None:
    # Two teams are out: roster 1 tagged by this test, roster 2 tagged in the fixture.
    report = sync_season(FakeClient(tagged_rosters()), conn, 2026, LEAGUE_ID, week=3)
    assert report.frozen == 2

    week, holdings, frozen_at = snapshot(conn, team_id(conn, 1))
    assert week == 3 and frozen_at is not None
    by_id = {h["sleeper_player_id"]: h for h in holdings}
    assert len(by_id) == 9
    assert by_id["4034"]["slot"] == "starter"
    assert by_id["4034"]["lineup_position"] == "QB"
    assert by_id["10881"]["slot"] == "ir"
    assert by_id["4943"]["slot"] == "taxi"
    assert "0" not in by_id


def test_a_later_sync_with_a_changed_roster_leaves_the_snapshot_alone(conn) -> None:
    payload = tagged_rosters()
    sync_season(FakeClient(payload), conn, 2026, LEAGUE_ID, week=3)
    team = team_id(conn, 1)
    before = snapshot(conn, team)

    payload[0]["players"] = ["4034", "99999"]
    payload[0]["starters"] = ["4034", "0", "0", "0", "0", "0", "0", "0", "0"]
    payload[0]["reserve"] = []
    payload[0]["taxi"] = []
    report = sync_season(FakeClient(payload), conn, 2026, LEAGUE_ID, week=4)

    assert report.frozen == 0
    assert snapshot(conn, team) == before
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.final_rosters where team_id = %s", (team,)
        )
        assert cur.fetchone()[0] == 1
    # roster_holdings still tracks Sleeper for an eliminated team; only the snapshot
    # is frozen, and consumers read the snapshot.
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id from public.roster_holdings where team_id = %s "
            "order by sleeper_player_id",
            (team,),
        )
        assert [row[0] for row in cur.fetchall()] == ["4034", "99999"]


def test_an_adjudicated_elimination_freezes_without_any_sleeper_tag(conn) -> None:
    """The Adjudicator writes its ruling into team_season_state, not through the sync.
    The next sync observes it and takes the snapshot."""
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    team = team_id(conn, 1)
    assert snapshot(conn, team) is None

    with conn.cursor() as cur:
        cur.execute(
            "update public.team_season_state set is_eliminated = true, eliminated_week = 2, "
            "elimination_source = 'adjudicator' where team_id = %s",
            (team,),
        )
    report = sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)

    assert report.frozen == 1
    week, holdings, _ = snapshot(conn, team)
    assert week == 2 and len(holdings) == 9


def test_a_live_team_has_no_final_roster_row(conn) -> None:
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    assert snapshot(conn, team_id(conn, 1)) is None
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.final_rosters")
        # Only roster 2, the one the fixture tags, is out.
        assert cur.fetchone()[0] == 1


def test_an_eliminated_team_with_an_empty_roster_freezes_an_empty_snapshot(conn) -> None:
    """Roster 2 is tagged eliminated and Sleeper reports no players at all. An empty
    array is the honest snapshot: it is what the team held when it went out, and
    refusing to freeze would leave the team unfrozen forever."""
    sync_season(FakeClient(rosters()), conn, 2026, LEAGUE_ID, week=3)
    week, holdings, frozen_at = snapshot(conn, team_id(conn, 2))
    assert week == 3 and holdings == [] and frozen_at is not None
```

- [ ] **Step 2: Run the tests red**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_final_rosters.py -v`

Expected: FAIL, `ImportError: cannot import name 'holdings_payload' from
'ultimate_guillotine.sleeper.roster_state'`.

- [ ] **Step 3: Add `holdings_payload` and `FinalRosterRepository` to `roster_state.py`**

Append to `sleeper/roster_state.py`, below `TeamStateRepository`:

```python
def holdings_payload(holdings: tuple[Holding, ...]) -> list[dict[str, object]]:
    """The body of a final-roster snapshot, in classification order.

    A plain list of plain dicts rather than the frozen dataclasses, because this
    goes into a ``jsonb`` column and comes back out of it as exactly this shape
    for the board to render. Order is the order ``classify_holdings`` produced:
    starters by lineup index, then ir, taxi, bench.
    """
    return [
        {
            "sleeper_player_id": holding.sleeper_player_id,
            "slot": holding.slot,
            "slot_index": holding.slot_index,
            "lineup_position": holding.lineup_position,
        }
        for holding in holdings
    ]


class FinalRosterRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def freeze(
        self,
        season_id: int,
        team_id: int,
        eliminated_week: int | None,
        holdings: tuple[Holding, ...],
        now: datetime,
    ) -> bool:
        """Snapshot a team's holdings the first time it is seen eliminated.

        ``do nothing`` is the whole rule: the first write wins forever. Later
        syncs keep updating ``roster_holdings`` for the team -- managers go on
        dropping and adding after they are out -- but the roster they were
        eliminated with never moves, and no code path updates or deletes this
        row. Returns True only when this call is the one that wrote it, so the
        caller can report how many teams froze on this run.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.final_rosters
                  (season_id, team_id, eliminated_week, holdings, frozen_at)
                values (%s, %s, %s, %s, %s)
                on conflict (season_id, team_id) do nothing
                """,
                (
                    season_id,
                    team_id,
                    eliminated_week,
                    Jsonb(holdings_payload(holdings)),
                    now,
                ),
            )
            return cur.rowcount == 1
```

`Jsonb` and `datetime` are already imported by Task 6's Step 5; `psycopg` and `Holding`
are already in this module.

- [ ] **Step 4: Freeze inside `sync_season`**

In `sleeper/sync.py`, add `frozen: int` to `SyncReport`:

```python
@dataclass(frozen=True)
class SyncReport:
    members: int
    teams: int
    holdings: int
    states: int
    frozen: int
```

Add `FinalRosterRepository` to the `roster_state` import, initialise
`final_repo = FinalRosterRepository(conn)` and `frozen_count = 0` beside the other two
repositories just before the roster loop, and add this immediately after the
`state_repo.upsert(...)` call inside the loop:

```python
            # The Adjudicator writes its ruling straight into team_season_state, so the
            # first sync that *observes* an elimination -- from either source -- is what
            # takes the snapshot. A second observation is a no-op.
            if merged.is_eliminated and final_repo.freeze(
                season_id, team_id, merged.eliminated_week, classification.holdings, now
            ):
                frozen_count += 1
```

The return becomes:

```python
    return SyncReport(len(member_ids), teams_synced, holdings_written, states_written,
                      frozen_count)
```

- [ ] **Step 5: Report it from the CLI**

In `cli/sleeper.py`'s `cmd_sync`, replace the `print` with:

```python
            print(
                f"sleeper sync: {report.members} members, {report.teams} teams, "
                f"{report.holdings} holdings, {report.states} team states, "
                f"{report.frozen} rosters frozen"
            )
```

- [ ] **Step 6: Run green, lint, commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres pnpm test:agents && pnpm lint:agents`

Expected: the six new tests pass, and Task 6's `tests/sleeper/test_sync_league_data.py`
still passes with the extra `SyncReport` field (it reads `report.holdings` and
`report.states` by name, not by position).

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/roster_state.py \
        packages/league-automation/src/ultimate_guillotine/sleeper/sync.py \
        packages/league-automation/src/ultimate_guillotine/cli/sleeper.py \
        packages/league-automation/tests/sleeper/test_final_rosters.py
git commit -m "feat: freeze an eliminated team's final roster exactly once"
```

### Task 8: Write `public.player_projections`

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/projections.py`
- Create: `packages/league-automation/tests/sleeper/test_projections.py`

**Interfaces:**
- Consumes: `SleeperClient.get_projections`, `score_stat_line`, `scoring_version`, `preset_drift`, `DRIFT_POINTS`, `DRIFT_SHARE`.
- Produces:
  - `MIN_PROJECTION_ROWS = 200`.
  - `@dataclass(frozen=True) class ProjectionRow: sleeper_player_id: str; stat_line: dict[str, float]; pts_ppr: Decimal | None; pts_half_ppr: Decimal | None; pts_std: Decimal | None; projected_at: datetime`.
  - `load_projections(payload: list[dict], week: int, now: datetime) -> list[ProjectionRow]`.
  - `@dataclass(frozen=True) class ProjectionReport: rows: int; scored: int; unscored: int; scoring_version: str; drift_share: Decimal; drift_flagged: bool`.
  - `ProjectionRepository(conn)` with `.upsert_many(season, week, rows, scoring_settings, version, now) -> ProjectionReport`, `.rescore(season, week, scoring_settings, version, now) -> ProjectionReport`, and `.flag_coverage(season, week, run_coverage_pct, flagged) -> None`.
  - `sync_projections(client, conn, season, week, scoring_settings, now, rescore=False) -> ProjectionReport` — one transaction; refuses a thin payload before writing anything.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/sleeper/test_projections.py
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from ultimate_guillotine.sleeper.projections import (
    ProjectionRepository,
    load_projections,
    sync_projections,
)
from ultimate_guillotine.sleeper.scoring import scoring_version

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "projections_2026_w1.json"
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
SETTINGS = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "sleeper" / "league_2026.json").read_text()
)["scoring_settings"]


def payload() -> list[dict]:
    return json.loads(FIXTURE.read_text())


class FakeProjClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls = 0

    def get_projections(self, season: int, week: int) -> list[dict]:
        self.calls += 1
        return self.rows


def bulk(rows: list[dict], count: int) -> list[dict]:
    """Pad the fixture past MIN_PROJECTION_ROWS with distinct player ids."""
    out = list(rows)
    template = rows[0]
    for index in range(count):
        out.append({**template, "player_id": f"pad-{index}"})
    return out


def test_load_parses_the_recorded_shape() -> None:
    rows = load_projections(payload(), week=1, now=NOW)
    by_id = {r.sleeper_player_id: r for r in rows}
    assert set(by_id) == {"4943", "7611", "9488", "12517", "12713", "SEA", "10881"}
    assert by_id["4943"].stat_line["pass_yd"] == 243.94
    assert by_id["9488"].pts_ppr == Decimal("19.69")
    assert by_id["9488"].pts_half_ppr == Decimal("16.28")
    assert by_id["9488"].pts_std == Decimal("12.86")
    # updated_at is epoch milliseconds.
    assert by_id["4943"].projected_at == datetime.fromtimestamp(1788963030.547, tz=UTC)


def test_load_skips_rows_for_another_week_or_another_category() -> None:
    rows = payload()
    rows[0] = {**rows[0], "week": 2}
    rows[1] = {**rows[1], "category": "stat"}
    rows[2] = {**rows[2], "stats": {}}
    loaded = load_projections(rows, week=1, now=NOW)
    assert {r.sleeper_player_id for r in loaded} == {"12517", "12713", "SEA", "10881"}


def test_sync_writes_points_from_the_league_settings(conn) -> None:
    client = FakeProjClient(bulk(payload(), 250))
    report = sync_projections(client, conn, 2026, 1, SETTINGS, NOW)
    assert report.rows == 257 and report.scoring_version == scoring_version(SETTINGS)
    with conn.cursor() as cur:
        cur.execute(
            "select league_points, pts_ppr, scoring_version, source, projected_at "
            "from public.player_projections where season = 2026 and week = 1 "
            "and sleeper_player_id = '9488'"
        )
        points, ppr, version, source, projected_at = cur.fetchone()
    # 6.83*1 + 94.17*0.1 + 0.53*6 + 1.85*0.1 + 0.03*-2 + 6.83*0.0 = 19.552 -> 19.55
    assert points == Decimal("19.55")
    assert ppr == Decimal("19.69") and source == "sleeper"
    assert version == scoring_version(SETTINGS) and projected_at is not None


def test_a_stat_line_the_league_cannot_score_stays_null_not_zero(conn) -> None:
    sync_projections(FakeProjClient(bulk(payload(), 250)), conn, 2026, 1, SETTINGS, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select league_points from public.player_projections "
            "where season = 2026 and week = 1 and sleeper_player_id = '10881'"
        )
        assert cur.fetchone()[0] is None


def test_a_thin_payload_is_refused_before_anything_is_written(conn) -> None:
    sync_projections(FakeProjClient(bulk(payload(), 250)), conn, 2026, 1, SETTINGS, NOW)
    with pytest.raises(RuntimeError, match="too few"):
        sync_projections(FakeProjClient(payload()), conn, 2026, 1, SETTINGS, NOW)
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.player_projections where week = 1")
        assert cur.fetchone()[0] == 257


def test_an_empty_payload_is_refused(conn) -> None:
    with pytest.raises(RuntimeError, match="too few"):
        sync_projections(FakeProjClient([]), conn, 2026, 1, SETTINGS, NOW)


def test_repeated_runs_produce_identical_rows(conn) -> None:
    client = FakeProjClient(bulk(payload(), 250))
    sync_projections(client, conn, 2026, 1, SETTINGS, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, projected_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        first = cur.fetchall()
    sync_projections(client, conn, 2026, 1, SETTINGS, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, projected_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        assert cur.fetchall() == first


def test_rescore_recomputes_from_stored_stat_lines_without_refetching(conn) -> None:
    client = FakeProjClient(bulk(payload(), 250))
    sync_projections(client, conn, 2026, 1, SETTINGS, NOW)
    client.calls = 0
    doubled = {**SETTINGS, "rec": 2.0}
    report = sync_projections(client, conn, 2026, 1, doubled, NOW, rescore=True)
    assert client.calls == 0 and report.scoring_version == scoring_version(doubled)
    with conn.cursor() as cur:
        cur.execute(
            "select league_points, scoring_version from public.player_projections "
            "where week = 1 and sleeper_player_id = '9488'"
        )
        points, version = cur.fetchone()
    assert points == Decimal("26.38")  # 19.55 + 6.83 extra reception points
    assert version == scoring_version(doubled)


def test_flag_coverage_marks_the_runs_rows(conn) -> None:
    sync_projections(FakeProjClient(bulk(payload(), 250)), conn, 2026, 1, SETTINGS, NOW)
    ProjectionRepository(conn).flag_coverage(2026, 1, Decimal("81.25"), flagged=True)
    with conn.cursor() as cur:
        cur.execute(
            "select distinct coverage_flagged, run_coverage_pct "
            "from public.player_projections where week = 1"
        )
        assert cur.fetchall() == [(True, Decimal("81.25"))]
```

- [ ] **Step 2: Run the tests red**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_projections.py -v`

Expected: FAIL, `ModuleNotFoundError: No module named 'ultimate_guillotine.sleeper.projections'`.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/sleeper/projections.py
"""Fetch, score, and store one NFL week of Sleeper player projections.

The raw stat map is kept verbatim so a scoring change can be replayed without
refetching, and so a wrong scoring rule is a bug that can be corrected rather
than data that has to be re-downloaded.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.scoring import (
    DRIFT_POINTS,
    DRIFT_SHARE,
    preset_drift,
    score_stat_line,
    scoring_version,
)

#: A live week has roughly 9,400 rows. Anything under this is a broken payload, not a
#: quiet week, and writing it would zero out a week that already had good numbers.
MIN_PROJECTION_ROWS = 200

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class ProjectionRow:
    sleeper_player_id: str
    stat_line: dict[str, float]
    pts_ppr: Decimal | None
    pts_half_ppr: Decimal | None
    pts_std: Decimal | None
    projected_at: datetime


@dataclass(frozen=True)
class ProjectionReport:
    rows: int
    scored: int
    unscored: int
    scoring_version: str
    drift_share: Decimal
    drift_flagged: bool


def _preset(stats: dict[str, object], key: str) -> Decimal | None:
    value = stats.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _projected_at(record: dict[str, object], now: datetime) -> datetime:
    """Sleeper timestamps projections in epoch milliseconds."""
    for key in ("updated_at", "last_modified"):
        raw = record.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return datetime.fromtimestamp(float(raw) / 1000.0, tz=UTC)
    return now


def load_projections(
    payload: list[dict[str, object]], week: int, now: datetime
) -> list[ProjectionRow]:
    """Parse the recorded projections shape into rows, dropping anything off-week."""
    rows: list[ProjectionRow] = []
    for record in payload:
        if not isinstance(record, dict) or record.get("category") != "proj":
            continue
        player_id = record.get("player_id")
        stats = record.get("stats")
        if not isinstance(player_id, str) or not player_id:
            continue
        if not isinstance(stats, dict) or not stats:
            continue
        record_week = record.get("week")
        if isinstance(record_week, int) and record_week != week:
            continue
        numeric = {
            key: float(value)
            for key, value in stats.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if not numeric:
            continue
        rows.append(
            ProjectionRow(
                sleeper_player_id=player_id,
                stat_line=numeric,
                pts_ppr=_preset(stats, "pts_ppr"),
                pts_half_ppr=_preset(stats, "pts_half_ppr"),
                pts_std=_preset(stats, "pts_std"),
                projected_at=_projected_at(record, now),
            )
        )
    return rows


def _report(
    scored_points: list[Decimal | None], lines: list[dict[str, float]], version: str
) -> ProjectionReport:
    scored = [p for p in scored_points if p is not None]
    drifted = 0
    compared = 0
    for points, line in zip(scored_points, lines, strict=True):
        drift = preset_drift(points, line)
        if drift is None:
            continue
        compared += 1
        if drift > DRIFT_POINTS:
            drifted += 1
    share = Decimal(drifted) / Decimal(compared) if compared else Decimal(0)
    return ProjectionReport(
        rows=len(scored_points),
        scored=len(scored),
        unscored=len(scored_points) - len(scored),
        scoring_version=version,
        drift_share=share.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        drift_flagged=share > DRIFT_SHARE,
    )


class ProjectionRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_many(
        self,
        season: int,
        week: int,
        rows: list[ProjectionRow],
        scoring_settings: dict[str, object],
        version: str,
        now: datetime,
    ) -> ProjectionReport:
        points = [score_stat_line(r.stat_line, scoring_settings) for r in rows]
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.player_projections
                  (season, week, sleeper_player_id, stat_line, league_points, pts_ppr,
                   pts_half_ppr, pts_std, scoring_version, source, coverage_flagged,
                   run_coverage_pct, projected_at, synced_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'sleeper', false, null, %s, %s)
                on conflict (season, week, sleeper_player_id) do update set
                  stat_line = excluded.stat_line, league_points = excluded.league_points,
                  pts_ppr = excluded.pts_ppr, pts_half_ppr = excluded.pts_half_ppr,
                  pts_std = excluded.pts_std, scoring_version = excluded.scoring_version,
                  source = excluded.source, coverage_flagged = false,
                  run_coverage_pct = null, projected_at = excluded.projected_at,
                  synced_at = excluded.synced_at
                """,
                [
                    (season, week, row.sleeper_player_id, json.dumps(row.stat_line),
                     value, row.pts_ppr, row.pts_half_ppr, row.pts_std, version,
                     row.projected_at, now)
                    for row, value in zip(rows, points, strict=True)
                ],
            )
        return _report(points, [r.stat_line for r in rows], version)

    def rescore(
        self,
        season: int,
        week: int,
        scoring_settings: dict[str, object],
        version: str,
        now: datetime,
    ) -> ProjectionReport:
        """Recompute points from stored stat lines. No network call."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, stat_line from public.player_projections "
                "where season = %s and week = %s order by sleeper_player_id",
                (season, week),
            )
            stored = cur.fetchall()
            points = [score_stat_line(line, scoring_settings) for _pid, line in stored]
            cur.executemany(
                """
                update public.player_projections
                set league_points = %s, scoring_version = %s, synced_at = %s
                where season = %s and week = %s and sleeper_player_id = %s
                """,
                [
                    (value, version, now, season, week, pid)
                    for (pid, _line), value in zip(stored, points, strict=True)
                ],
            )
        return _report(points, [line for _pid, line in stored], version)

    def flag_coverage(
        self, season: int, week: int, run_coverage_pct: Decimal, flagged: bool
    ) -> None:
        """Stamp the run's coverage on every row it wrote. Flagged, never withheld."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update public.player_projections
                set coverage_flagged = %s, run_coverage_pct = %s
                where season = %s and week = %s
                """,
                (flagged, run_coverage_pct, season, week),
            )


def sync_projections(
    client: SleeperClient,
    conn: psycopg.Connection,
    season: int,
    week: int,
    scoring_settings: dict[str, object],
    now: datetime,
    rescore: bool = False,
) -> ProjectionReport:
    """Fetch (or reuse) a week of projections, score them, and upsert.

    ``rescore`` skips the fetch entirely: the stat lines are already stored, and
    a scoring change is not a reason to ask Sleeper for the same numbers again.
    """
    version = scoring_version(scoring_settings)
    repo = ProjectionRepository(conn)
    if rescore:
        with conn.transaction():
            return repo.rescore(season, week, scoring_settings, version, now)
    rows = load_projections(client.get_projections(season, week), week, now)
    if len(rows) < MIN_PROJECTION_ROWS:
        # Refuse before opening the transaction: a 200 with no body must never zero
        # out a week that already has good projections.
        raise RuntimeError(
            f"sleeper returned too few projections for {season} week {week}: {len(rows)}"
        )
    with conn.transaction():
        return repo.upsert_many(season, week, rows, scoring_settings, version, now)
```

- [ ] **Step 4: Run green, lint, commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_projections.py -v && pnpm lint:agents`

Expected: 9 passed.

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/projections.py \
        packages/league-automation/tests/sleeper/test_projections.py
git commit -m "feat: write scored Sleeper player projections per NFL week"
```

### Task 9: Team-week projections and the 95 percent coverage gate

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/team_projections.py`
- Create: `packages/league-automation/tests/sleeper/test_team_projections.py`

**Interfaces:**
- Consumes: `public.roster_holdings`, `public.player_projections`, `public.team_season_state`, `public.seasons.roster_positions`.
- Produces:
  - `COVERAGE_GATE = Decimal("95")`.
  - `@dataclass(frozen=True) class TeamWeekProjection: team_id: int; projected_points: Decimal; starter_slots: int; filled_slots: int; empty_slots: int; starters_projected: int; missing_projections: int; coverage_pct: Decimal; is_provisional: bool`.
  - `@dataclass(frozen=True) class StarterTally: team_id: int; filled_slots: int; starters_projected: int; projected_points: Decimal; is_eliminated: bool`.
  - `coverage_pct(starters_projected: int, filled_slots: int) -> Decimal` — `100.00` when `filled_slots` is zero.
  - `run_coverage(tallies: list[StarterTally]) -> Decimal` — over non-eliminated teams only.
  - `build_team_week(tallies: list[StarterTally], starter_slots: int, run_pct: Decimal) -> list[TeamWeekProjection]`.
  - `TeamWeekRepository(conn)` with `.tally(season_id, season_year, week) -> list[StarterTally]`, `.starter_slots(season_id) -> int`, `.upsert_many(season_id, week, rows, now) -> int`.
  - `recompute_team_week(conn, season_id, season_year, week, now) -> tuple[list[TeamWeekProjection], Decimal]`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/sleeper/test_team_projections.py
from datetime import UTC, datetime
from decimal import Decimal

from ultimate_guillotine.sleeper.team_projections import (
    StarterTally,
    build_team_week,
    coverage_pct,
    recompute_team_week,
    run_coverage,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def test_coverage_is_projected_over_filled_and_100_when_nothing_is_filled() -> None:
    assert coverage_pct(9, 9) == Decimal("100.00")
    assert coverage_pct(8, 9) == Decimal("88.89")
    assert coverage_pct(0, 0) == Decimal("100.00")


def test_run_coverage_ignores_eliminated_teams() -> None:
    tallies = [
        StarterTally(1, 9, 9, Decimal("110.00"), is_eliminated=False),
        StarterTally(2, 9, 8, Decimal("100.00"), is_eliminated=False),
        StarterTally(3, 9, 0, Decimal("0.00"), is_eliminated=True),
    ]
    assert run_coverage(tallies) == Decimal("94.44")
    healthy = [t for t in tallies if not t.is_eliminated]
    assert run_coverage(healthy + [StarterTally(4, 9, 9, Decimal("90"), False)]) == (
        Decimal("96.30")
    )


def test_empty_slots_contribute_zero_and_leave_coverage_alone() -> None:
    # 7 of 9 slots filled, all 7 projected: coverage is 100, empty_slots is 2.
    rows = build_team_week(
        [StarterTally(1, 7, 7, Decimal("98.40"), False)], starter_slots=9,
        run_pct=Decimal("100.00"),
    )
    row = rows[0]
    assert row.empty_slots == 2 and row.filled_slots == 7
    assert row.coverage_pct == Decimal("100.00") and row.missing_projections == 0
    assert row.projected_points == Decimal("98.40") and not row.is_provisional


def test_a_missing_projection_lowers_coverage_and_flags_provisional() -> None:
    rows = build_team_week(
        [StarterTally(1, 9, 8, Decimal("101.00"), False)], starter_slots=9,
        run_pct=Decimal("99.00"),
    )
    row = rows[0]
    assert row.missing_projections == 1
    assert row.coverage_pct == Decimal("88.89") and row.is_provisional


def test_a_failing_run_gate_makes_every_team_provisional() -> None:
    rows = build_team_week(
        [StarterTally(1, 9, 9, Decimal("120.00"), False)], starter_slots=9,
        run_pct=Decimal("81.25"),
    )
    assert rows[0].coverage_pct == Decimal("100.00") and rows[0].is_provisional


def test_recompute_sums_starter_projections_for_the_week(conn) -> None:
    season_id, team_id = _seed(conn)
    rows, run_pct = recompute_team_week(conn, season_id, 2026, 1, NOW)
    row = next(r for r in rows if r.team_id == team_id)
    # 20.00 (starter with a projection) + 0 for the starter without one.
    assert row.projected_points == Decimal("20.00")
    assert (row.filled_slots, row.starters_projected, row.missing_projections) == (2, 1, 1)
    assert row.empty_slots == 7 and row.coverage_pct == Decimal("50.00")
    assert row.is_provisional and run_pct == Decimal("50.00")
    with conn.cursor() as cur:
        cur.execute(
            "select projected_points, coverage_pct, is_provisional, computed_at "
            "from public.team_week_projections where team_id = %s and week = 1",
            (team_id,),
        )
        assert cur.fetchone() == (Decimal("20.00"), Decimal("50.00"), True, NOW)


def test_recompute_is_idempotent(conn) -> None:
    season_id, team_id = _seed(conn)
    recompute_team_week(conn, season_id, 2026, 1, NOW)
    recompute_team_week(conn, season_id, 2026, 1, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.team_week_projections where team_id = %s",
            (team_id,),
        )
        assert cur.fetchone()[0] == 1


def _seed(conn) -> tuple[int, int]:
    """One season with nine starter slots, one team, two starters, one projection."""
    with conn.cursor() as cur:
        cur.execute(
            "update public.seasons set roster_positions = "
            "'[\"QB\",\"RB\",\"RB\",\"WR\",\"WR\",\"TE\",\"FLEX\",\"K\",\"DEF\"]' "
            "where year = 2026 returning id"
        )
        season_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.members (display_name) values ('Coverage Member') "
            "returning id"
        )
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values (%s, %s, 'u', 901, 'T') returning id",
            (season_id, member_id),
        )
        team_id = cur.fetchone()[0]
        cur.executemany(
            "insert into public.roster_holdings (season_id, team_id, sleeper_player_id, "
            "slot, slot_index, lineup_position, synced_at) values (%s, %s, %s, %s, %s, "
            "%s, now())",
            [
                (season_id, team_id, "p1", "starter", 0, "QB"),
                (season_id, team_id, "p2", "starter", 1, "RB"),
                (season_id, team_id, "p3", "bench", None, None),
            ],
        )
        cur.executemany(
            "insert into public.player_projections (season, week, sleeper_player_id, "
            "stat_line, league_points, scoring_version, projected_at, synced_at) "
            "values (2026, 1, %s, '{}'::jsonb, %s, 'v1', now(), now())",
            [("p1", Decimal("20.00")), ("p3", Decimal("30.00"))],
        )
    return season_id, team_id
```

- [ ] **Step 2: Run the tests red**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_team_projections.py -v`

Expected: FAIL, `ModuleNotFoundError: No module named 'ultimate_guillotine.sleeper.team_projections'`.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/sleeper/team_projections.py
"""Team projected points for one week, and the 95 percent coverage gate.

An empty starter slot and a missing projection both add zero points, and the
difference between them is the whole point of this module: nobody can project a
slot a manager left blank, so it does not count against coverage, while a filled
slot with no projection does.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import psycopg

#: Below this, a team's number is not shown: consumers render "projection unavailable".
COVERAGE_GATE = Decimal("95")

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class StarterTally:
    team_id: int
    filled_slots: int
    starters_projected: int
    projected_points: Decimal
    is_eliminated: bool


@dataclass(frozen=True)
class TeamWeekProjection:
    team_id: int
    projected_points: Decimal
    starter_slots: int
    filled_slots: int
    empty_slots: int
    starters_projected: int
    missing_projections: int
    coverage_pct: Decimal
    is_provisional: bool


def coverage_pct(starters_projected: int, filled_slots: int) -> Decimal:
    """Share of filled starter slots that carry a projection.

    A roster with nothing in its starting lineup is fully covered, not zero
    covered: there is nothing left to project.
    """
    if filled_slots <= 0:
        return Decimal("100.00")
    share = Decimal(starters_projected) / Decimal(filled_slots) * Decimal(100)
    return share.quantize(_CENTS, rounding=ROUND_HALF_UP)


def run_coverage(tallies: list[StarterTally]) -> Decimal:
    """One coverage number for the whole run, over non-eliminated teams only."""
    live = [t for t in tallies if not t.is_eliminated]
    filled = sum(t.filled_slots for t in live)
    projected = sum(t.starters_projected for t in live)
    return coverage_pct(projected, filled)


def build_team_week(
    tallies: list[StarterTally], starter_slots: int, run_pct: Decimal
) -> list[TeamWeekProjection]:
    """Turn tallies into rows. A failing run gate makes every row provisional."""
    run_failed = run_pct < COVERAGE_GATE
    rows: list[TeamWeekProjection] = []
    for tally in tallies:
        team_pct = coverage_pct(tally.starters_projected, tally.filled_slots)
        rows.append(
            TeamWeekProjection(
                team_id=tally.team_id,
                projected_points=tally.projected_points.quantize(
                    _CENTS, rounding=ROUND_HALF_UP
                ),
                starter_slots=starter_slots,
                filled_slots=tally.filled_slots,
                empty_slots=max(starter_slots - tally.filled_slots, 0),
                starters_projected=tally.starters_projected,
                missing_projections=tally.filled_slots - tally.starters_projected,
                coverage_pct=team_pct,
                is_provisional=team_pct < COVERAGE_GATE or run_failed,
            )
        )
    return rows


class TeamWeekRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def starter_slots(self, season_id: int) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "select jsonb_array_length(roster_positions) from public.seasons "
                "where id = %s",
                (season_id,),
            )
            row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def tally(self, season_id: int, season_year: int, week: int) -> list[StarterTally]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select t.id,
                       count(h.sleeper_player_id) as filled,
                       count(p.league_points) as projected,
                       coalesce(sum(p.league_points), 0) as points,
                       coalesce(bool_or(s.is_eliminated), false) as eliminated
                from public.teams t
                left join public.roster_holdings h
                  on h.team_id = t.id and h.season_id = t.season_id
                     and h.slot = 'starter'
                left join public.player_projections p
                  on p.sleeper_player_id = h.sleeper_player_id
                     and p.season = %s and p.week = %s
                left join public.team_season_state s
                  on s.team_id = t.id and s.season_id = t.season_id
                where t.season_id = %s
                group by t.id
                order by t.id
                """,
                (season_year, week, season_id),
            )
            return [StarterTally(*row) for row in cur.fetchall()]

    def upsert_many(
        self, season_id: int, week: int, rows: list[TeamWeekProjection], now: datetime
    ) -> int:
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.team_week_projections
                  (season_id, team_id, week, projected_points, starter_slots,
                   filled_slots, empty_slots, starters_projected, missing_projections,
                   coverage_pct, is_provisional, computed_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, team_id, week) do update set
                  projected_points = excluded.projected_points,
                  starter_slots = excluded.starter_slots,
                  filled_slots = excluded.filled_slots,
                  empty_slots = excluded.empty_slots,
                  starters_projected = excluded.starters_projected,
                  missing_projections = excluded.missing_projections,
                  coverage_pct = excluded.coverage_pct,
                  is_provisional = excluded.is_provisional,
                  computed_at = excluded.computed_at
                """,
                [
                    (season_id, r.team_id, week, r.projected_points, r.starter_slots,
                     r.filled_slots, r.empty_slots, r.starters_projected,
                     r.missing_projections, r.coverage_pct, r.is_provisional, now)
                    for r in rows
                ],
            )
        return len(rows)


def recompute_team_week(
    conn: psycopg.Connection, season_id: int, season_year: int, week: int, now: datetime
) -> tuple[list[TeamWeekProjection], Decimal]:
    """Recompute every team's week row and return the rows plus the run's coverage."""
    repo = TeamWeekRepository(conn)
    tallies = repo.tally(season_id, season_year, week)
    run_pct = run_coverage(tallies)
    rows = build_team_week(tallies, repo.starter_slots(season_id), run_pct)
    repo.upsert_many(season_id, week, rows, now)
    return rows, run_pct
```

- [ ] **Step 4: Run green, lint, commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_team_projections.py -v && pnpm lint:agents`

Expected: 7 passed.

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/team_projections.py \
        packages/league-automation/tests/sleeper/test_team_projections.py
git commit -m "feat: compute team week projections and the 95 percent coverage gate"
```

### Task 10: `ug sleeper projections`, ops notes, and the cron jobs

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/ops/transitions.py`
- Create: `packages/league-automation/tests/ops/test_transitions.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/data/repositories.py` (add `RunRepository.last_finished_status`)
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`
- Create: `packages/league-automation/tests/cli/test_sleeper_projections.py`
- Modify: `hermes/guillotine/cron.yaml`
- Create: `hermes/guillotine/scripts/guillotine_sleeper_projections.sh.template`
- Create: `hermes/guillotine/scripts/guillotine_nfl_state.sh.template`

**Interfaces:**
- Consumes: `current_week`, `sync_projections`, `recompute_team_week`, `ProjectionRepository.flag_coverage`, `COVERAGE_GATE`, `HermesNotifier.ops`, `run_scheduled`.
- Produces:
  - `transition_note(agent: str, previous_status: str | None, current_status: str, now: datetime) -> str | None` — one line on the succeeded-to-failed transition and one on recovery, `None` otherwise.
  - `RunRepository.last_finished_status(agent: str) -> str | None` — the newest `succeeded` or `failed` status for that agent.
  - `ug sleeper projections [--week N] [--rescore] [--quiet]` recording agent `projections-sync`.
  - Four new cron jobs in `hermes/guillotine/cron.yaml`.

- [ ] **Step 1: Write the failing transition tests**

```python
# packages/league-automation/tests/ops/test_transitions.py
from datetime import UTC, datetime

from ultimate_guillotine.ops.transitions import transition_note

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def test_one_note_on_the_transition_into_failure() -> None:
    note = transition_note("projections-sync", "succeeded", "failed", NOW)
    assert note == "projections-sync: run failed at 2026-09-09 12:00 UTC"


def test_consecutive_failures_are_silent() -> None:
    assert transition_note("projections-sync", "failed", "failed", NOW) is None


def test_one_note_on_recovery() -> None:
    note = transition_note("projections-sync", "failed", "succeeded", NOW)
    assert note == "projections-sync: recovered at 2026-09-09 12:00 UTC"


def test_steady_success_and_a_first_ever_failure_are_handled() -> None:
    assert transition_note("nfl-state", "succeeded", "succeeded", NOW) is None
    assert transition_note("nfl-state", None, "failed", NOW) is not None
    assert transition_note("nfl-state", None, "succeeded", NOW) is None
```

- [ ] **Step 2: Write the failing CLI test**

```python
# packages/league-automation/tests/cli/test_sleeper_projections.py
import subprocess
import sys


def test_sleeper_help_lists_every_subcommand() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "sleeper", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    for name in ("sync", "players", "projections", "state"):
        assert name in result.stdout


def test_projections_help_lists_week_and_rescore() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "sleeper",
         "projections", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--week" in result.stdout and "--rescore" in result.stdout
```

- [ ] **Step 3: Run both red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/ops/test_transitions.py packages/league-automation/tests/cli/test_sleeper_projections.py -v`

Expected: FAIL on the missing `ops.transitions` module and on `projections` not appearing
in the `ug sleeper` help.

- [ ] **Step 4: Implement the transition helper and the repository method**

```python
# packages/league-automation/src/ultimate_guillotine/ops/transitions.py
"""One ops note per status change, not one per failed run.

A Sleeper outage lasts as long as it lasts, and a job that fires every five
minutes would otherwise post a wall of identical notes. The 5-minute
guillotine-health job already reports sustained staleness, so this module says
something only when the answer to "is it working?" actually changes.
"""

from datetime import datetime


def transition_note(
    agent: str, previous_status: str | None, current_status: str, now: datetime
) -> str | None:
    """Return the note to post, or None when nothing changed worth saying."""
    stamp = f"{now:%Y-%m-%d %H:%M} UTC"
    if current_status == "failed" and previous_status != "failed":
        return f"{agent}: run failed at {stamp}"
    if current_status == "succeeded" and previous_status == "failed":
        return f"{agent}: recovered at {stamp}"
    return None
```

Add to `RunRepository` in `data/repositories.py`:

```python
    def last_finished_status(self, agent: str) -> str | None:
        """The newest terminal status for ``agent``, ignoring runs still running."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select status from private.agent_runs
                where agent = %s and status in ('succeeded', 'failed')
                order by id desc limit 1
                """,
                (agent,),
            )
            row = cur.fetchone()
            return row[0] if row else None
```

- [ ] **Step 5: Implement the CLI command**

Add to `cli/sleeper.py`'s imports:

```python
from decimal import Decimal

from ultimate_guillotine.data.repositories import RunRepository
from ultimate_guillotine.ops.transitions import transition_note
from ultimate_guillotine.sleeper.projections import ProjectionRepository, sync_projections
from ultimate_guillotine.sleeper.team_projections import COVERAGE_GATE, recompute_team_week
```

Register the subparser inside `register`:

```python
    proj_parser = sleeper_sub.add_parser("projections", help="sync weekly projections")
    proj_parser.add_argument("--week", type=int, default=None, help="week to sync")
    proj_parser.add_argument(
        "--rescore",
        action="store_true",
        help="recompute points from stored stat lines without refetching",
    )
    proj_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    proj_parser.set_defaults(handler=cmd_projections)
```

and the handler:

```python
def cmd_projections(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)
    client = SleeperClient(httpx.Client())
    previous = RunRepository(conn).last_finished_status("projections-sync")

    def action(run_id: int) -> int:
        state = current_week(client, conn, now)
        week = args.week if args.week is not None else state.week
        with conn.cursor() as cur:
            cur.execute(
                "select id, scoring_settings from public.seasons where year = %s",
                (SYNC_YEAR,),
            )
            row = cur.fetchone()
        if row is None:
            raise ValueError(f"no season row for year {SYNC_YEAR}")
        season_id, scoring_settings = row
        if not scoring_settings:
            raise ValueError("seasons.scoring_settings is empty; run ug sleeper sync first")

        report = sync_projections(
            client, conn, state.season, week, scoring_settings, now, rescore=args.rescore
        )
        rows, run_pct = recompute_team_week(conn, season_id, state.season, week, now)
        ProjectionRepository(conn).flag_coverage(
            state.season, week, run_pct, flagged=run_pct < COVERAGE_GATE
        )
        if run_pct < COVERAGE_GATE:
            provisional = sum(1 for r in rows if r.is_provisional)
            deps.notifier.ops(
                f"projections week {week}: coverage {run_pct}% is below "
                f"{COVERAGE_GATE}%; {provisional} teams marked provisional"
            )
        if report.drift_flagged:
            deps.notifier.ops(
                f"projections week {week}: {report.drift_share * Decimal(100):.1f}% of "
                f"scored players differ from the nearest Sleeper preset by more than 3 "
                f"points; check seasons.scoring_settings"
            )
        if not args.quiet:
            print(
                f"projections: week {week}, {report.rows} players "
                f"({report.unscored} unscored), coverage {run_pct}%"
            )
        return 0

    try:
        exit_code = run_scheduled(conn, "projections-sync", now, action)
    except Exception:
        note = transition_note("projections-sync", previous, "failed", now)
        if note:
            deps.notifier.ops(note)
        raise
    if exit_code is not None:
        note = transition_note("projections-sync", previous, "succeeded", now)
        if note:
            deps.notifier.ops(note)
    return exit_code or 0
```

Apply the same `previous` / `transition_note` wrapper to `cmd_sync` (agent `sleeper-sync`)
and `cmd_state` (agent `nfl-state`), so all three jobs report status changes the same way.

- [ ] **Step 6: Add the cron jobs and script templates**

Append to `hermes/guillotine/cron.yaml`:

```yaml
  - name: guillotine-nfl-state
    agent: nfl-state
    schedule: "every 10m"
    script: guillotine_nfl_state.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 30
  # The four projections jobs share the agent name `projections-sync` on purpose: the
  # per-agent, per-minute idempotency key in run_scheduled absorbs an overlap between the
  # baseline and a game-window fire, and health checks the agent, so the */30 baseline
  # keeps all four rows fresh. Cron fields below are the Mac mini's LOCAL time
  # (America/New_York), not UTC.
  - name: guillotine-sleeper-projections
    agent: projections-sync
    schedule: "*/30 * * * *"
    script: guillotine_sleeper_projections.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 90
  - name: guillotine-sleeper-projections-thursday
    agent: projections-sync
    schedule: "*/5 20-23 * * 4"
    script: guillotine_sleeper_projections.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 90
  - name: guillotine-sleeper-projections-sunday
    agent: projections-sync
    schedule: "*/5 13-23 * * 0"
    script: guillotine_sleeper_projections.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 90
  - name: guillotine-sleeper-projections-monday
    agent: projections-sync
    schedule: "*/5 20-23 * * 1"
    script: guillotine_sleeper_projections.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 90
```

`hermes/guillotine/scripts/guillotine_nfl_state.sh.template`:

```bash
#!/bin/bash
set -euo pipefail
cd "__REPO__"
exec /opt/homebrew/bin/uv run --project packages/league-automation ug sleeper state --quiet
```

`hermes/guillotine/scripts/guillotine_sleeper_projections.sh.template`:

```bash
#!/bin/bash
set -euo pipefail
cd "__REPO__"
exec /opt/homebrew/bin/uv run --project packages/league-automation \
  ug sleeper projections --quiet
```

`install.sh` needs no change: it already copies every `*.sh.template` and re-registers
every job in the manifest.

- [ ] **Step 7: Run green, install, verify one live run, commit**

Run:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres \
  pnpm test:agents && pnpm lint:agents && bash hermes/guillotine/install.sh
uv run --project packages/league-automation ug sleeper state
uv run --project packages/league-automation ug sleeper sync
uv run --project packages/league-automation ug sleeper projections
```

Expected: tests pass; `install.sh` registers nine jobs; `ug sleeper state` prints
`nfl state: 2026 regular week <n>`; `ug sleeper sync` prints eighteen teams with a
non-zero holdings count; `ug sleeper projections` prints a player count in the thousands
and a coverage percentage. Record the coverage number in the commit message body.

```bash
git add packages/league-automation hermes/guillotine
git commit -m "feat: add ug sleeper projections, ops transition notes, and cron jobs"
```

### Task 11: `build_roster_index` reads `roster_holdings`

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/trades/resolve.py:68-97`
- Create: `packages/league-automation/tests/trades/test_roster_index.py`

**Interfaces:**
- Consumes: `public.roster_holdings`, `public.teams`, `public.seasons`; `SleeperClient.get_rosters` as the fallback.
- Produces:
  - `HOLDINGS_MAX_AGE = timedelta(hours=6)`.
  - `build_roster_index(client, conn, league_id, season, now=None) -> RosterIndex` — unchanged name, unchanged `RosterIndex` shape, one new optional `now` keyword for testing. Reads `roster_holdings` first; falls back to one `client.get_rosters` call when the season has no holdings rows or `max(synced_at)` is older than `HOLDINGS_MAX_AGE`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/trades/test_roster_index.py
from datetime import UTC, datetime, timedelta

from ultimate_guillotine.sleeper.models import SleeperRoster
from ultimate_guillotine.trades.resolve import build_roster_index

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class FakeRosterClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        self.calls += 1
        return [SleeperRoster(roster_id=911, owner_id="u", players=["from-sleeper"])]


def _seed(conn, synced_at: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        season_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.members (display_name) values ('Index Member') returning id"
        )
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values (%s, %s, 'u', 911, 'T') returning id",
            (season_id, member_id),
        )
        team_id = cur.fetchone()[0]
        cur.executemany(
            "insert into public.roster_holdings (season_id, team_id, sleeper_player_id, "
            "slot, synced_at) values (%s, %s, %s, %s, %s)",
            [
                (season_id, team_id, "p1", "starter", synced_at),
                (season_id, team_id, "p2", "bench", synced_at),
                (season_id, team_id, "p3", "ir", synced_at),
            ],
        )
    return member_id


def test_index_reads_the_holdings_table_without_calling_sleeper(conn) -> None:
    member_id = _seed(conn, NOW - timedelta(minutes=5))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 0
    assert index.holdings[member_id] == frozenset({"p1", "p2", "p3"})
    assert index.holds(member_id, "p2") and not index.holds(member_id, "p9")


def test_stale_holdings_fall_back_to_one_sleeper_call(conn) -> None:
    member_id = _seed(conn, NOW - timedelta(hours=7))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 1
    assert index.holdings[member_id] == frozenset({"from-sleeper"})


def test_no_holdings_at_all_falls_back(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Empty Member') returning id"
        )
        member_id = cur.fetchone()[0]
        cur.execute("select id from public.seasons where year = 2026")
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values ((select id from public.seasons "
            "where year = 2026), %s, 'u', 911, 'T')",
            (member_id,),
        )
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 1 and index.holdings[member_id] == frozenset({"from-sleeper"})


def test_an_unknown_season_gives_an_empty_index(conn) -> None:
    client = FakeRosterClient()
    assert build_roster_index(client, conn, "league", 1999, now=NOW).holdings == {}
```

- [ ] **Step 2: Run the tests red**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_roster_index.py -v`

Expected: FAIL, `TypeError: build_roster_index() got an unexpected keyword argument 'now'`.

- [ ] **Step 3: Implement**

Replace `build_roster_index` in `trades/resolve.py` with the following, adding
`from datetime import UTC, datetime, timedelta` to the imports:

```python
#: Past this, the holdings cache is not trusted for trade resolution and the registrar
#: pays for one live Sleeper call rather than resolving against a stalled roster.
HOLDINGS_MAX_AGE = timedelta(hours=6)


def build_roster_index(
    client: SleeperClient,
    conn: psycopg.Connection,
    league_id: str,
    season: int,
    now: datetime | None = None,
) -> RosterIndex:
    """Map each member to the Sleeper player ids they currently hold.

    Reads ``public.roster_holdings``, which the 10-minute sync keeps current: a
    🚨 alert arriving during a Sleeper outage still resolves against the last
    good rows, and no alert costs a Sleeper call. The ``client`` remains for one
    guard -- an empty or stale cache falls back to one live fetch, so a stalled
    sync never blocks the registrar.
    """
    now = now or datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            select max(h.synced_at)
            from public.roster_holdings h
            join public.seasons s on s.id = h.season_id
            where s.year = %s
            """,
            (season,),
        )
        row = cur.fetchone()
    freshest = row[0] if row else None
    if freshest is None or now - freshest > HOLDINGS_MAX_AGE:
        return _index_from_sleeper(client, conn, league_id, season)

    with conn.cursor() as cur:
        cur.execute(
            """
            select t.member_id, h.sleeper_player_id
            from public.roster_holdings h
            join public.teams t on t.id = h.team_id
            join public.seasons s on s.id = h.season_id
            where s.year = %s
            """,
            (season,),
        )
        rows = cur.fetchall()
    holdings: dict[int, set[str]] = {}
    for member_id, player_id in rows:
        holdings.setdefault(member_id, set()).add(player_id)
    return RosterIndex({m: frozenset(ids) for m, ids in holdings.items()})


def _index_from_sleeper(
    client: SleeperClient, conn: psycopg.Connection, league_id: str, season: int
) -> RosterIndex:
    """The pre-holdings path: one live fetch joined to teams by sleeper_roster_id."""
    rosters = client.get_rosters(league_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.sleeper_roster_id, t.member_id
            from public.teams t
            join public.seasons s on s.id = t.season_id
            where s.year = %s
            """,
            (season,),
        )
        roster_to_member = {row[0]: row[1] for row in cur.fetchall()}
    if not roster_to_member:
        return RosterIndex.empty()
    holdings: dict[int, frozenset[str]] = {}
    for roster in rosters:
        member_id = roster_to_member.get(roster.roster_id)
        if member_id is None:
            continue
        holdings[member_id] = frozenset(roster.players)
    return RosterIndex(holdings)
```

- [ ] **Step 4: Run the whole suite green, lint, commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres pnpm test:agents && pnpm lint:agents && supabase test db`

Expected: every test passes, including the existing `tests/trades/test_resolve.py`
(`RosterIndex`, `holds()`, and `resolve_extracted` are untouched) and the registrar tests.

```bash
git add packages/league-automation/src/ultimate_guillotine/trades/resolve.py \
        packages/league-automation/tests/trades/test_roster_index.py
git commit -m "feat: resolve trades against roster_holdings with a live Sleeper fallback"
```

### Task 12: `nickname` from `ug members aliases load`

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/trades/models.py:42-53`
- Modify: `packages/league-automation/src/ultimate_guillotine/data/repositories.py:480-538`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/members.py`
- Modify: `packages/league-automation/tests/data/test_repositories.py`
- Modify: `packages/league-automation/tests/cli/test_members.py`

**Interfaces:**
- Consumes: `public.members.nickname` (Task 2); the existing `MemberAliasRepository`, `MemberRef`, and `ug members` CLI.
- Produces:
  - `MemberRef` gains a fourth field `has_nickname: bool = False`. It is defaulted so the existing three-argument constructions in `tests/trades/test_resolve.py` and `tests/trades/test_registrar.py` keep working untouched, and trade-name resolution ignores it.
  - `MemberAliasRepository.replace_aliases(member_display_name, aliases)` additionally writes `public.members.nickname` — the first alias in the file's order, `null` for an empty list — inside the same savepoint as the alias rows, so a rejected load leaves the old nickname in place.
  - `MemberAliasRepository.all_members()` populates `has_nickname` from `nickname is not null`.
  - `ug members list` prints `<display_name>  <alias count>  <nickname|->` and never the nickname itself.

- [ ] **Step 1: Write the failing repository tests**

Append to `packages/league-automation/tests/data/test_repositories.py`:

```python
def test_replace_aliases_publishes_the_first_alias_as_the_nickname(conn) -> None:
    """The board and the Concierge label owners by nickname, so exactly one alias
    becomes public. The rest stay in private.member_aliases, which anon cannot read."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Nick One') returning id"
        )
        member_id = cur.fetchone()[0]
    repo = MemberAliasRepository(conn)

    repo.replace_aliases("Nick One", ["Benny", "The Hammer"])

    with conn.cursor() as cur:
        cur.execute("select nickname from public.members where id = %s", (member_id,))
        assert cur.fetchone()[0] == "Benny"
    member = next(m for m in repo.all_members() if m.member_id == member_id)
    assert member.has_nickname is True


def test_a_member_with_no_aliases_has_a_null_nickname(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Nick Two') returning id"
        )
        member_id = cur.fetchone()[0]
    repo = MemberAliasRepository(conn)

    repo.replace_aliases("Nick Two", ["Solo"])
    repo.replace_aliases("Nick Two", [])

    with conn.cursor() as cur:
        cur.execute("select nickname from public.members where id = %s", (member_id,))
        assert cur.fetchone()[0] is None
    member = next(m for m in repo.all_members() if m.member_id == member_id)
    assert member.has_nickname is False


def test_a_rejected_alias_load_leaves_the_old_nickname_in_place(conn) -> None:
    """The nickname write shares the savepoint with the alias rows: a load that
    collides on somebody else's alias must not strand a member half-renamed."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Nick Three'), ('Nick Four')"
        )
    repo = MemberAliasRepository(conn)
    repo.replace_aliases("Nick Three", ["keeper"])
    repo.replace_aliases("Nick Four", ["taken"])

    with pytest.raises(ValueError, match="already belongs to another member"):
        repo.replace_aliases("Nick Three", ["fresh", "taken"])

    with conn.cursor() as cur:
        cur.execute(
            "select nickname from public.members where display_name = 'Nick Three'"
        )
        assert cur.fetchone()[0] == "keeper"
```

- [ ] **Step 2: Write the failing CLI test**

Add `from ultimate_guillotine.trades.models import MemberRef` to the imports of
`packages/league-automation/tests/cli/test_members.py`, then append:

```python
class FakeListRepo:
    """One member with a nickname, one without."""

    def __init__(self, conn) -> None:
        pass

    def all_members(self):
        return [
            MemberRef(1, "Member01", ("Benny", "The Hammer"), True),
            MemberRef(2, "Member02", (), False),
        ]


def test_members_list_flags_who_has_a_nickname_without_printing_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Aliases are personal. The listing says whether a nickname exists and stops
    there, so a run of it can still be pasted into ops."""
    monkeypatch.setattr(members_cli, "build_deps", lambda: SimpleNamespace(conn=None))
    monkeypatch.setattr(members_cli, "MemberAliasRepository", FakeListRepo)

    assert members_cli.cmd_list(argparse.Namespace()) == 0

    out = capsys.readouterr().out
    assert "Member01  2  nickname" in out
    assert "Member02  0  -" in out
    assert "Benny" not in out and "Hammer" not in out
```

- [ ] **Step 3: Run the tests red**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/data/test_repositories.py packages/league-automation/tests/cli/test_members.py -v`

Expected: FAIL, `TypeError: MemberRef.__init__() takes 4 positional arguments but 5 were
given` in the CLI test and `AttributeError: 'MemberRef' object has no attribute
'has_nickname'` in the repository tests.

- [ ] **Step 4: Add the field to `MemberRef`**

Replace `MemberRef` in `trades/models.py` with:

```python
@dataclass(frozen=True)
class MemberRef:
    """A league member and the names resolution may match them by.

    Lives here rather than in ``trades.resolve`` so ``data.repositories`` can
    return one without importing the Sleeper HTTP client.

    ``has_nickname`` says only whether ``public.members.nickname`` is set. The
    value itself is deliberately absent: ``ug members list`` reports presence and
    nothing else, and trade resolution matches on ``aliases``, never on this.
    """

    member_id: int
    display_name: str
    aliases: tuple[str, ...]
    has_nickname: bool = False
```

- [ ] **Step 5: Write and read the nickname in `MemberAliasRepository`**

In `data/repositories.py`, replace the query in `all_members` and its row mapping with:

```python
    def all_members(self) -> list[MemberRef]:
        """Return every member with the aliases (if any) resolution matches them by."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select m.id, m.display_name, m.nickname is not null,
                    coalesce(array_agg(a.alias) filter (where a.alias is not null), '{}')
                from public.members m left join private.member_aliases a on a.member_id = m.id
                group by m.id, m.display_name, m.nickname order by m.id
                """
            )
            return [MemberRef(row[0], row[1], tuple(row[3]), row[2]) for row in cur.fetchall()]
```

and, in `replace_aliases`, add this as the last statement inside the
`with self._conn.transaction(), self._conn.cursor() as cur:` block, after the alias
insert loop:

```python
            # The first alias in the file's order is the public label. `wanted` is
            # keyed by normalized form but preserves first-appearance order, so this
            # is the member's first alias in its original spelling. An empty list
            # clears the nickname: a member with no aliases has no public label, and
            # consumers fall back to sleeper_display_name.
            cur.execute(
                "update public.members set nickname = %s where id = %s",
                (next(iter(wanted.values()), None), member_id),
            )
```

Update the method's docstring to say so, replacing its first paragraph with:

```python
        """Replace a member's aliases wholesale, returning how many rows were written.

        Also republishes ``public.members.nickname`` as the member's first alias --
        the one label the board and the Concierge are allowed to show. Every other
        alias stays in ``private.member_aliases``.
        """
```

Keep the rest of the existing docstring paragraphs exactly as they are.

- [ ] **Step 6: Flag it in `ug members list`**

Replace `cmd_list` in `cli/members.py` with:

```python
def cmd_list(args: argparse.Namespace) -> int:
    deps = build_deps()
    for member in MemberAliasRepository(deps.conn).all_members():
        flag = "nickname" if member.has_nickname else "-"
        print(f"{member.display_name}  {len(member.aliases)}  {flag}")
    return 0
```

The module docstring's promise still holds: this prints whether a nickname exists, never
what it is.

- [ ] **Step 7: Run the whole suite green, lint, commit**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres pnpm test:agents && pnpm lint:agents && supabase test db`

Expected: the four new tests pass, the existing alias tests in
`tests/data/test_repositories.py` still pass, and the trade resolution tests in
`tests/trades/` still pass on their three-argument `MemberRef` constructions.

```bash
git add packages/league-automation/src/ultimate_guillotine/trades/models.py \
        packages/league-automation/src/ultimate_guillotine/data/repositories.py \
        packages/league-automation/src/ultimate_guillotine/cli/members.py \
        packages/league-automation/tests/data/test_repositories.py \
        packages/league-automation/tests/cli/test_members.py
git commit -m "feat: publish each member's first alias as their nickname"
```

---

## Self-Review Notes

- **Spec coverage.** Tables and grants: Task 2. Cached season settings: Tasks 2, 6. `roster_holdings` slot rules, `"0"` empty slots, and the delete-on-drop: Tasks 4, 6. `team_season_state` FAAB recombination, record, points, and elimination precedence with `state_version`: Tasks 4, 6. Ben's frozen final rosters (`public.final_rosters`, snapshot once, never overwritten, consumers read it for eliminated teams): Tasks 2, 7, plus the Consumers section. Ben's owner labels (`members.sleeper_display_name` written by the sync, `members.nickname` written by the alias loader, nickname-else-display-name everywhere, bare username never): Tasks 2, 6, 12, plus Global Constraints and Consumers. `player_projections`, the dot product, the denylist, `scoring_version`, `--rescore`, and the preset drift note: Tasks 3, 8, 10. `team_week_projections`, empty versus missing slots, `coverage_pct`, `is_provisional`, and the 95 percent gate: Task 9, wired in Task 10. `nfl_state` and the 60-minute inline refresh: Task 5. Realtime publication and `replica identity full`: Task 2. Sync jobs and cadences: Task 10. Idempotency: asserted in Tasks 5, 6, 7, 8, 9. Failure behavior (abort, last good rows survive, thin payload refused, one note per transition): Tasks 8, 10. Trade Registrar change: Task 11. Privacy: no table, log line, or fixture in this plan carries a phone number, chat GUID, or message body; the one newly public personal field is `members.nickname`, which Ben asked for and which Task 12 exposes one alias at a time (see Spec issue 6).
- **Names used across tasks.** `get_projections`, `PROJECTIONS_URL`, `score_stat_line`, `scoring_version`, `preset_drift`, `SCORING_DENYLIST`, `DRIFT_POINTS`, `DRIFT_SHARE`, `Holding`, `RosterClassification`, `classify_holdings`, `TeamState`, `team_state_from_roster`, `Elimination`, `infer_elimination`, `merge_elimination`, `bumps_state_version`, `holdings_payload`, `SeasonSettingsRepository.cache`, `RosterHoldingRepository.replace_for_team`, `TeamStateRepository.get_elimination/.upsert`, `FinalRosterRepository.freeze`, `SleeperUser.sleeper_display_name`, `MemberRef.has_nickname`, `MemberAliasRepository.replace_aliases/.all_members`, `NflState`, `parse_nfl_state`, `NflStateRepository.upsert/.get`, `STATE_MAX_AGE`, `sync_nfl_state`, `current_week`, `ProjectionRow`, `load_projections`, `ProjectionReport`, `ProjectionRepository.upsert_many/.rescore/.flag_coverage`, `sync_projections`, `MIN_PROJECTION_ROWS`, `StarterTally`, `TeamWeekProjection`, `coverage_pct`, `run_coverage`, `build_team_week`, `TeamWeekRepository`, `recompute_team_week`, `COVERAGE_GATE`, `transition_note`, `RunRepository.last_finished_status`, `HOLDINGS_MAX_AGE`, `build_roster_index`, `_index_from_sleeper`.
- **`SyncReport` grows twice.** Task 6 adds `holdings` and `states`; Task 7 adds `frozen`. Every construction and every read is by keyword or by attribute name, never by position, so Task 7's field cannot silently shift Task 6's.
- **Rollout order** matches the spec: Task 2 ships the migration, Task 6 extends `ug sleeper sync` (watch two cycles in `#guillotine-ops` before continuing), Task 7 adds the freeze (verify against a team the Adjudicator has already ruled out before continuing), Tasks 8 to 10 add the projections job (confirm coverage passes for a full week before the board reads it), Task 11 switches the registrar. Task 12 is independent of the Sleeper jobs and may ship any time after Task 2 — but it must ship before the board renders owner labels, or every owner falls back to their Sleeper display name.

## Spec issues

Eight contradictions or gaps, each resolved in the plan rather than blocking on it.

1. **`private.projection_snapshots` was already created.** The spec says `public.player_projections` "supersedes the foundation's planned `private.projection_snapshots`, which is not created" — but `supabase/migrations/20260908210808_private_automation_schema.sql:100` created it on 2026-09-08. **Resolution:** Task 2's migration drops it. It is empty and no code references it (`grep -rn projection_snapshots packages/ apps/ services/ hermes/ scripts/` returns nothing), so a forward drop is cleaner than leaving a table nothing will ever write.
2. **Inferred elimination from `get_matchups` cannot be implemented yet.** The spec's inference rule is "a roster that has stopped appearing in `get_matchups` for the current week, or a roster whose Sleeper metadata Ben has tagged", while its own Open Question 1 asks whether an eliminated roster even stays in Sleeper. Those cannot both be settled. **Resolution:** Task 4's `infer_elimination` reads **only** the `metadata.eliminated` tag; matchup absence is not treated as elimination, because guessing wrong would provisionally eliminate live teams every bye week. The `elimination_source` column, the precedence rule, and `state_version` are all implemented, so adding the matchup rule later is a one-function change once Ben answers.
3. **The failure-note suppression window is not implementable without extra state.** The spec asks for one note on the succeeded-to-failed transition, one on recovery, and silence for "consecutive failures inside a 60-minute suppression window" — which implies a note may fire again after 60 minutes, but nothing records when the last note went out. **Resolution:** Task 10's `transition_note` posts on transitions only; consecutive failures are always silent. This is the spec's own stated justification ("the 5-minute `guillotine-health` job already reports sustained staleness") carried to its conclusion, and it needs no new column.
4. **`is_provisional` when the run gate fails but a team's own coverage is fine.** The spec sets `is_provisional = true` on "the affected `team_week_projections` rows" without saying which rows a failing *run* gate affects. **Resolution:** Task 9 sets `is_provisional = coverage_pct < 95 or run_coverage_pct < 95`, so a failing run makes every team provisional. A run-wide projection failure is not something one team escapes.
5. **Two smaller type mismatches.** The spec says `SleeperRoster`'s new `settings` and `metadata` fields take "the same null-to-empty validator `players` already has", but those are objects, not arrays — Task 4 gives them a null-to-empty-**dict** validator instead. And `team_season_state.faab_budget` is `not null` while its source, `seasons.waiver_budget`, is nullable — Task 4's `team_state_from_roster` records `0` for a league Sleeper is not running a FAAB budget for, which `faab_remaining` then reports honestly as `0 - faab_used`.
6. **Ben's nickname decision makes one alias public.** The alias file is git-ignored, `private.member_aliases` is unreachable by `anon`, and `cli/members.py`'s module docstring promises that "nothing here ever prints an alias back out" — but Ben's decision puts the first alias in `public.members.nickname`, which the public board reads with the `anon` key. **Resolution:** exactly one alias per member becomes public, in Task 12; every other alias stays private, and `ug members list` still reports presence rather than the value, so the CLI's promise holds. This is a deliberate choice of Ben's — the nickname is what the league calls each other on a board the league can already see — and it is recorded here so nobody re-privatises the column later thinking it was an accident.
7. **`members.display_name` already holds Sleeper's display name.** `sync_season` writes `user.display_name` into `public.members.display_name`, which is also the table's unique natural key and what the alias file's `sleeper_username` matches, so `sleeper_display_name` duplicates it on the day it ships. **Resolution:** keep both with different jobs. `display_name` is the key the sync upserts on and the alias loader matches; `sleeper_display_name` is the label consumers render and every sync refreshes. They diverge the moment an owner renames themselves in Sleeper, and the board then follows the rename while alias matching does not break. (A rename still creates a second `members` row, because the upsert keys on `display_name`; that is a pre-existing wart of the foundation schema and out of scope here.)
8. **The freeze needs a trigger `sync_season` can actually see.** The spec says the snapshot is taken "when a team's elimination is recorded", but the authoritative recorder — the Weekly Adjudicator — writes its ruling straight into `public.team_season_state` and never calls the sync. **Resolution:** Task 7 freezes on the first sync that *observes* `merge_elimination` returning eliminated, from either source. The snapshot lands within one 10-minute cycle of the ruling, `public.final_rosters` keeps a single writer, and `on conflict do nothing` makes every later observation a no-op. An eliminated team whose Sleeper roster is already empty freezes an empty array, which is the honest record of what it held when it went out.
