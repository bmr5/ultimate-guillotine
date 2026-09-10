# Player Card Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sleeper's 2026 auction and its executed transaction log become season-keyed rows in Supabase — `public.draft_picks`, `public.transactions`, `public.transaction_moves` — written by two new `ug sleeper` jobs on the Mac mini.

**Architecture:** Two script-only sync jobs in the existing `sleeper/` package, each shaped like `sleeper/scores.py`: fetch first, parse with a pure loader that is tested without a database, upsert on a natural key inside the transaction `run_scheduled` already holds, report counts only. One migration adds the three tables in the data layer's standard shape (identity key, RLS, anon select, worker insert/update, no delete). The web half of the feature is a separate plan, `2026-09-10-player-card-web.md`, which reads these tables and nothing else new.

**Tech Stack:** Python 3.12, psycopg 3, pydantic 2, httpx + respx, pytest, ruff (line length 100); Supabase migrations + pgTAP; Hermes cron manifest.

**Spec:** `docs/superpowers/specs/2026-09-10-player-card-design.md` — sections "What Sleeper Holds", "Tables", "Sync Jobs", and the Mac mini half of "Test and Rollout".

## Global Constraints

- Every command runs from the repository root. Python: `uv run --project packages/league-automation ...`. Suite: `pnpm test:agents` and `pnpm lint:agents`. Lines at or under 100 characters (ruff).
- DB-backed tests use the shared `conn` fixture (`packages/league-automation/tests/conftest.py`), which skips without `TEST_DATABASE_URL` and rolls back. The local Supabase stack is at `postgresql://postgres:postgres@127.0.0.1:54322/postgres`; export it as `TEST_DATABASE_URL` before claiming any DB task done.
- Every new public table: identity primary key, `created_at timestamptz not null default now()`, RLS enabled, `revoke all` then `grant select` to `anon, authenticated`, a `"Public <table> are readable"` select policy, an `"Automation writes <table>"` policy `for all to automation_worker using (true) with check (true)`, `grant select, insert, update` to `automation_worker`, **no delete grant**, **not** added to `supabase_realtime`.
- Only `status = 'complete'` Sleeper transactions are stored. `week` is Sleeper's `leg`. `occurred_at` is `status_updated`, else `created`. Unknown `type` and unresolvable `roster_id` are counted and skipped, never a failed run.
- The draft job is a no-op (`skipped`) until the draft's `status` is `complete`; then it refuses an empty payload, fewer than `settings.teams × settings.rounds` picks, any pick whose `metadata.amount` is not an integer ≥ 1, and any `roster_id` with no `teams` row.
- Reports print counts only — never a name, never a nickname.
- New agent names, recorded by `run_scheduled` and pinned by the cron manifest test: `draft-sync` and `transactions-sync`.
- TDD: write the failing test, watch it fail, implement, watch it pass, commit. Commit directly on `main` (this repo merges freely; keep every gate green).

---

## File Structure

**Create**

| Path | Responsibility |
| --- | --- |
| `supabase/migrations/20260910190000_player_card.sql` | The three tables, policies, grants. |
| `supabase/tests/player_card.sql` | pgTAP: shape, RLS, policies, privileges, keys, no realtime. |
| `packages/league-automation/src/ultimate_guillotine/sleeper/values.py` | Two tiny coercions Sleeper payloads need everywhere: `as_int`, `from_millis`. |
| `packages/league-automation/src/ultimate_guillotine/sleeper/teams.py` | `teams_by_roster_id(conn, season_id)` — the one hop from roster ids to team ids, shared by scores, draft, transactions. |
| `packages/league-automation/src/ultimate_guillotine/sleeper/draft.py` | `DraftPick`, `load_draft_picks`, `DraftRepository`, `sync_draft`. |
| `packages/league-automation/src/ultimate_guillotine/sleeper/transactions.py` | `Transaction`, `Move`, `FaabMove`, `load_transactions`, `TransactionRepository`, `sync_transactions`. |
| `packages/league-automation/tests/fixtures/sleeper/draft_2026.json` | The real 2026 draft record, trimmed. |
| `packages/league-automation/tests/fixtures/sleeper/draft_picks_2026.json` | The real 162 picks, `picked_by` anonymised to the roster fixture's `user-NN`. |
| `packages/league-automation/tests/fixtures/sleeper/transactions_2026_w1.json` | The real eight week-1 records, `creator` anonymised. |
| `packages/league-automation/tests/sleeper/test_values.py` | `as_int` / `from_millis`. |
| `packages/league-automation/tests/sleeper/test_teams.py` | The roster→team hop against the real table. |
| `packages/league-automation/tests/sleeper/test_draft.py` | Loader (pure) and sync (DB). |
| `packages/league-automation/tests/sleeper/test_transactions.py` | Loader (pure) and sync (DB). |
| `packages/league-automation/tests/cli/test_sleeper_draft.py` | `ug sleeper draft` around its sync. |
| `packages/league-automation/tests/cli/test_sleeper_transactions.py` | `ug sleeper transactions` around its sync. |
| `hermes/guillotine/scripts/guillotine_sleeper_draft.sh.template` | Cron script. |
| `hermes/guillotine/scripts/guillotine_sleeper_transactions.sh.template` | Cron script. |

**Modify**

| Path | Change |
| --- | --- |
| `packages/league-automation/src/ultimate_guillotine/sleeper/models.py` | `SleeperLeague.draft_id`; new `SleeperDraft`. |
| `packages/league-automation/src/ultimate_guillotine/sleeper/client.py` | `get_draft`, `get_draft_picks`, `get_transactions`. |
| `packages/league-automation/src/ultimate_guillotine/sleeper/scores.py:170-183` | `ScoreRepository.teams_by_roster_id` delegates to `sleeper/teams.py`. |
| `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py` | Register `draft` and `transactions`; `cmd_draft`, `cmd_transactions`. |
| `packages/league-automation/tests/sleeper/conftest.py` | `FakeClient` serves the three new fixtures. |
| `packages/league-automation/tests/sleeper/test_client.py` | Three respx tests. |
| `packages/league-automation/tests/fixtures/sleeper/league_2026.json` | Gains `"draft_id"`. |
| `hermes/guillotine/cron.yaml` | Two jobs. |
| `packages/league-automation/tests/hermes/test_cron_manifest.py` | Agent set; pin the two jobs. |
| `docs/runbooks/mac-mini.md` | Jobs table, first-run list, one paragraph. |

---

### Task 1: Migration and pgTAP test

**Files:**
- Create: `supabase/migrations/20260910190000_player_card.sql`
- Create: `supabase/tests/player_card.sql`

**Interfaces:**
- Produces: tables `public.draft_picks`, `public.transactions`, `public.transaction_moves` with the exact columns below; every later task's SQL names them.

- [ ] **Step 1: Bring the local database up to date**

The local stack is running but five migrations behind. Run:

```bash
npx supabase migration up --local
npx supabase migration list --local
```

Expected: the second command shows every local version with a matching remote value, the newest being `20260910170000`.

- [ ] **Step 2: Write the failing pgTAP test**

`supabase/tests/player_card.sql`:

```sql
-- The player card's three tables: the auction, the executed transaction log, and the
-- per-player index over it. Spec: docs/superpowers/specs/2026-09-10-player-card-design.md.
--
-- One file for the three because they land in one migration and share one shape: RLS on,
-- readable by the anon key, written by automation_worker with no delete grant, and none of
-- them published to Realtime — the mark depends on roster_holdings, which already streams,
-- and the card fetches on open.
begin;
select plan(19);

-- `supabase db reset` seeds only public.seasons; the row-level assertions need a team.
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

select has_table('public', 'draft_picks', 'draft_picks table exists');
select has_table('public', 'transactions', 'transactions table exists');
select has_table('public', 'transaction_moves', 'transaction_moves table exists');

select is(
  (select relrowsecurity from pg_class where oid = 'public.draft_picks'::regclass),
  true, 'draft_picks has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.transactions'::regclass),
  true, 'transactions has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.transaction_moves'::regclass),
  true, 'transaction_moves has row level security enabled'
);

select policies_are(
  'public', 'draft_picks',
  array['Public draft_picks are readable', 'Automation writes draft_picks']
);
select policies_are(
  'public', 'transactions',
  array['Public transactions are readable', 'Automation writes transactions']
);
select policies_are(
  'public', 'transaction_moves',
  array['Public transaction_moves are readable', 'Automation writes transaction_moves']
);

-- No DELETE on any of the three: none of them is a cache, and roster_holdings stays the one
-- public table the worker may delete from.
select table_privs_are(
  'public', 'draft_picks', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on public.draft_picks and nothing else'
);
select table_privs_are(
  'public', 'transactions', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on public.transactions and nothing else'
);
select table_privs_are(
  'public', 'transaction_moves', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on public.transaction_moves and nothing else'
);

-- The natural keys the syncs upsert on.
select col_is_unique(
  'public', 'draft_picks', array['season_id', 'sleeper_player_id'],
  'a player is drafted once per season'
);
select col_is_unique(
  'public', 'draft_picks', array['season_id', 'sleeper_draft_id', 'pick_no'],
  'a pick number is used once per draft'
);
select col_is_unique(
  'public', 'transactions', array['sleeper_transaction_id'],
  'one row per Sleeper transaction'
);
select col_is_unique(
  'public', 'transaction_moves', array['transaction_id', 'sleeper_player_id', 'action'],
  'one move per player per side of a transaction'
);

-- An auction pick without a price is a malformed payload, not a free player.
select throws_ok(
  $$insert into public.draft_picks
      (season_id, team_id, sleeper_player_id, sleeper_draft_id, pick_no, round, draft_slot,
       amount, drafted_at, synced_at)
    values ((select id from public.seasons where year = 2026),
            (select id from public.teams where sleeper_roster_id = 999),
            'pgtap-player', 'pgtap-draft', 1, 1, 1, 0, now(), now())$$,
  '23514', null, 'draft_picks refuses an amount below 1'
);

-- A transaction is one of four kinds; a fifth is skipped by the sync, never stored.
select throws_ok(
  $$insert into public.transactions
      (season_id, sleeper_transaction_id, kind, week, occurred_at, raw, synced_at)
    values ((select id from public.seasons where year = 2026),
            'pgtap-tx', 'gift', 1, now(), '{}', now())$$,
  '23514', null, 'transactions refuses an unknown kind'
);

-- None of the three is published: the card fetches on open, the mark rides on roster_holdings.
select is(
  (select count(*)::int from pg_publication_tables
     where pubname = 'supabase_realtime' and schemaname = 'public'
       and tablename in ('draft_picks', 'transactions', 'transaction_moves')),
  0, 'the player card tables are not published to supabase_realtime'
);

select * from finish();
rollback;
```

- [ ] **Step 3: Run it to verify it fails**

Run: `npx supabase test db --local`
Expected: `player_card.sql` fails on `has_table ... draft_picks` (the other files still pass).

- [ ] **Step 4: Write the migration**

`supabase/migrations/20260910190000_player_card.sql`:

```sql
-- The player card's data: what a player went for at the auction and everything that has
-- happened to him since. Spec: docs/superpowers/specs/2026-09-10-player-card-design.md.
--
-- Three tables in the data layer's standard shape (see 20260909151435_league_data_layer.sql):
-- identity key, created_at, RLS on, select for anon/authenticated behind a "Public <table> are
-- readable" policy, an "Automation writes <table>" policy for automation_worker with
-- select/insert/update and no delete. None is a cache — a pick, an executed transaction, and
-- a move are facts — so nothing here is ever deleted, and none of them joins the Realtime
-- publication: the mark rides on roster_holdings, which already streams, and the card fetches
-- on open.
--
-- Everything is keyed by season_id. Ben (2026-09-10): "season data and trades and draft should
-- stay within season for this feature."

-- One row per auction pick. team_id is the pick's roster_id resolved through
-- teams (season_id, sleeper_roster_id); position is what Sleeper recorded on the pick, which is
-- what the auction ranked by; drafted_at is the draft's start_time, the same on every row, so
-- the journey's first entry has a date. No foreign key to public.players, for the reason
-- roster_holdings has none: the directory keeps skill positions only.
create table public.draft_picks (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  sleeper_player_id text not null,
  sleeper_draft_id text not null,
  pick_no int not null,
  round int not null,
  draft_slot int not null,
  position text,
  -- An auction league: a pick without a price is a malformed payload, not a free player.
  amount int not null check (amount >= 1),
  drafted_at timestamptz not null,
  synced_at timestamptz not null,
  unique (season_id, sleeper_player_id),
  unique (season_id, sleeper_draft_id, pick_no)
);
create index draft_picks_team_idx on public.draft_picks (team_id);

-- One row per completed Sleeper transaction. week is Sleeper's own `leg`, never the clock;
-- occurred_at is status_updated, else created; team_ids are roster_ids resolved to teams;
-- faab_moves entries are {"amount", "from_team_id", "to_team_id"}; waiver_bid is
-- settings.waiver_bid on a claim and null otherwise; raw is the record verbatim so a later
-- reparse never needs a refetch, on the same reasoning as player_projections.stat_line.
-- Failed waiver bids are not stored: 2025 had 1,269 of them, and they say nothing about a
-- player's journey.
create table public.transactions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  sleeper_transaction_id text not null unique,
  kind text not null check (kind in ('trade', 'waiver', 'free_agent', 'commissioner')),
  week int not null,
  occurred_at timestamptz not null,
  team_ids bigint[] not null default '{}',
  faab_moves jsonb not null default '[]',
  waiver_bid int,
  raw jsonb not null,
  synced_at timestamptz not null
);
create index transactions_season_week_idx on public.transactions (season_id, week);
create index transactions_season_occurred_idx on public.transactions (season_id, occurred_at);

-- One row per player per side of a transaction: every entry in `adds` is an add for its
-- roster's team and every entry in `drops` a drop for its. A trade yields an add for the
-- receiver and a drop for the sender per player. This is the per-player index the card reads;
-- transactions alone would need a JSON scan.
create table public.transaction_moves (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  transaction_id bigint not null references public.transactions (id),
  season_id bigint not null references public.seasons (id),
  sleeper_player_id text not null,
  team_id bigint not null references public.teams (id),
  action text not null check (action in ('add', 'drop')),
  unique (transaction_id, sleeper_player_id, action)
);
create index transaction_moves_season_player_idx
  on public.transaction_moves (season_id, sleeper_player_id);

alter table public.draft_picks enable row level security;
alter table public.transactions enable row level security;
alter table public.transaction_moves enable row level security;

revoke all on public.draft_picks from anon, authenticated;
revoke all on public.transactions from anon, authenticated;
revoke all on public.transaction_moves from anon, authenticated;
grant select on public.draft_picks to anon, authenticated;
grant select on public.transactions to anon, authenticated;
grant select on public.transaction_moves to anon, authenticated;

create policy "Public draft_picks are readable" on public.draft_picks
  for select using (true);
create policy "Automation writes draft_picks" on public.draft_picks
  for all to automation_worker using (true) with check (true);
create policy "Public transactions are readable" on public.transactions
  for select using (true);
create policy "Automation writes transactions" on public.transactions
  for all to automation_worker using (true) with check (true);
create policy "Public transaction_moves are readable" on public.transaction_moves
  for select using (true);
create policy "Automation writes transaction_moves" on public.transaction_moves
  for all to automation_worker using (true) with check (true);

-- No delete grant on any of the three; roster_holdings stays the one public table the worker
-- may delete from.
grant select, insert, update on public.draft_picks to automation_worker;
grant select, insert, update on public.transactions to automation_worker;
grant select, insert, update on public.transaction_moves to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;
```

- [ ] **Step 5: Apply it and run the pgTAP suite**

Run:

```bash
npx supabase migration up --local
npx supabase test db --local
```

Expected: every file passes, `player_card.sql` reporting 19 of 19.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20260910190000_player_card.sql supabase/tests/player_card.sql
git commit -m "feat(db): draft picks, transactions and transaction moves for the player card"
```

---

### Task 2: Fixtures, models, and client methods

**Files:**
- Create: `packages/league-automation/tests/fixtures/sleeper/draft_2026.json`
- Create: `packages/league-automation/tests/fixtures/sleeper/draft_picks_2026.json`
- Create: `packages/league-automation/tests/fixtures/sleeper/transactions_2026_w1.json`
- Modify: `packages/league-automation/tests/fixtures/sleeper/league_2026.json`
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/models.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/client.py`
- Modify: `packages/league-automation/tests/sleeper/test_client.py`
- Modify: `packages/league-automation/tests/sleeper/conftest.py`

**Interfaces:**
- Produces: `SleeperLeague.draft_id: str | None`; `SleeperDraft(draft_id, type, status, start_time, last_picked, settings)` with `.teams`, `.rounds`, `.started_at`; `SleeperClient.get_draft(draft_id) -> SleeperDraft`, `.get_draft_picks(draft_id) -> list[dict]`, `.get_transactions(league_id, week) -> list[dict]`; `FakeClient` serving all three.

- [ ] **Step 1: Generate the three fixtures from the live API**

The roster fixture names rosters 1–18 owned by `user-01`…`user-18`, so the real payloads only need their user ids rewritten. Run from the repository root:

```bash
uv run --project packages/league-automation python - <<'EOF'
import json, urllib.request
from pathlib import Path

def get(path):
    with urllib.request.urlopen("https://api.sleeper.app/v1" + path, timeout=30) as r:
        return json.load(r)

out = Path("packages/league-automation/tests/fixtures/sleeper")
league_id, draft_id = "1389372259260452864", "1389372259260452865"
rosters = get(f"/league/{league_id}/rosters")
user_for = {r["owner_id"]: f"user-{r['roster_id']:02d}" for r in rosters}

draft = get(f"/draft/{draft_id}")
trimmed = {k: draft[k] for k in ("draft_id", "type", "status", "start_time", "last_picked",
                                 "season", "league_id", "settings")}
(out / "draft_2026.json").write_text(json.dumps(trimmed, indent=1) + "\n")

picks = []
for p in get(f"/draft/{draft_id}/picks"):
    m = p["metadata"]
    picks.append({
        "draft_id": p["draft_id"], "draft_slot": p["draft_slot"], "is_keeper": p["is_keeper"],
        "pick_no": p["pick_no"], "round": p["round"], "roster_id": p["roster_id"],
        "player_id": p["player_id"], "picked_by": user_for[p["picked_by"]],
        "metadata": {k: m.get(k) for k in ("amount", "position", "player_id",
                                           "first_name", "last_name", "team")},
    })
(out / "draft_picks_2026.json").write_text(json.dumps(picks, indent=1) + "\n")

txs = get(f"/league/{league_id}/transactions/1")
for t in txs:
    if t.get("creator") in user_for:
        t["creator"] = user_for[t["creator"]]
(out / "transactions_2026_w1.json").write_text(json.dumps(txs, indent=1) + "\n")
print(len(picks), "picks;", len(txs), "transactions;", draft["status"], draft["settings"]["teams"], draft["settings"]["rounds"])
EOF
```

Expected: `162 picks; 8 transactions; complete 18 9`. Then add the draft id to the league fixture:

```bash
uv run --project packages/league-automation python - <<'EOF'
import json
from pathlib import Path
p = Path("packages/league-automation/tests/fixtures/sleeper/league_2026.json")
d = json.loads(p.read_text())
d["draft_id"] = "1389372259260452865"
p.write_text(json.dumps(d, indent=1) + "\n")
EOF
```

Inspect `transactions_2026_w1.json`: it must hold three `trade` records and five `free_agent` records, all `"status": "complete"`, and one trade with `"adds": null`.

- [ ] **Step 2: Write the failing client tests**

Append to `packages/league-automation/tests/sleeper/test_client.py`:

```python
@respx.mock
def test_get_draft_parses_status_and_dimensions() -> None:
    respx.get("https://api.sleeper.app/v1/draft/1389372259260452865").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "draft_2026.json").read_text())
        )
    )
    draft = SleeperClient(httpx.Client()).get_draft("1389372259260452865")
    assert (draft.type, draft.status) == ("auction", "complete")
    assert (draft.teams, draft.rounds) == (18, 9)
    assert draft.started_at is not None and draft.started_at.year == 2026


@respx.mock
def test_get_draft_picks_returns_the_raw_list() -> None:
    respx.get("https://api.sleeper.app/v1/draft/1389372259260452865/picks").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "draft_picks_2026.json").read_text())
        )
    )
    picks = SleeperClient(httpx.Client()).get_draft_picks("1389372259260452865")
    assert len(picks) == 162
    assert picks[0]["metadata"]["amount"] == "53"


@respx.mock
def test_get_transactions_asks_for_the_week() -> None:
    route = respx.get(
        "https://api.sleeper.app/v1/league/1389372259260452864/transactions/1"
    ).mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "transactions_2026_w1.json").read_text())
        )
    )
    records = SleeperClient(httpx.Client()).get_transactions("1389372259260452864", 1)
    assert route.called
    assert len(records) == 8
    assert {r["type"] for r in records} == {"trade", "free_agent"}


def test_the_league_fixture_names_its_draft() -> None:
    league = SleeperLeague.model_validate(
        json.loads((FIXTURES / "league_2026.json").read_text())
    )
    assert league.draft_id == "1389372259260452865"
```

Add `from ultimate_guillotine.sleeper.models import SleeperLeague` to the file's imports.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_client.py -v`
Expected: the four new tests fail — `AttributeError: 'SleeperClient' object has no attribute 'get_draft'` and `draft_id` missing.

- [ ] **Step 4: Extend the models**

In `packages/league-automation/src/ultimate_guillotine/sleeper/models.py`, change the imports and add `draft_id` to `SleeperLeague`:

```python
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator


class SleeperLeague(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    league_id: str
    name: str
    season: str
    total_rosters: int
    scoring_settings: dict[str, object] = {}
    roster_positions: list[str] = []
    settings: dict[str, object] = {}
    #: The league's canonical draft. Listing ``/league/{id}/drafts`` is the wrong key: the
    #: 2025 league also carries an abandoned one-pick draft.
    draft_id: str | None = None
```

Append the draft model at the end of the file:

```python
class SleeperDraft(BaseModel, frozen=True):
    """The draft record behind ``league.draft_id``: its kind, its status, its dimensions."""

    model_config = ConfigDict(extra="ignore")

    draft_id: str
    type: str
    status: str
    start_time: int | None = None
    last_picked: int | None = None
    settings: dict[str, object] = {}

    @field_validator("settings", mode="before")
    @classmethod
    def _no_settings_is_an_empty_map(cls, value: object) -> object:
        return {} if value is None else value

    def _setting(self, key: str) -> int | None:
        value = self.settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    @property
    def teams(self) -> int | None:
        return self._setting("teams")

    @property
    def rounds(self) -> int | None:
        return self._setting("rounds")

    @property
    def started_at(self) -> datetime | None:
        """When the draft opened, from Sleeper's millisecond epoch.

        Falls back to ``last_picked`` when Sleeper never stamped a start, so a
        completed draft always has a date for the journey's first entry.
        """
        millis = self.start_time if self.start_time is not None else self.last_picked
        if millis is None:
            return None
        return datetime.fromtimestamp(millis / 1000, tz=UTC)
```

- [ ] **Step 5: Extend the client**

In `packages/league-automation/src/ultimate_guillotine/sleeper/client.py`, import `SleeperDraft` alongside the other models and add after `get_rosters`:

```python
    def get_draft(self, draft_id: str) -> SleeperDraft:
        """Fetch one draft's record: type, status, start time, and dimensions."""
        response = self._http.get(f"/draft/{draft_id}")
        response.raise_for_status()
        return SleeperDraft.model_validate(response.json())

    def get_draft_picks(self, draft_id: str) -> list[dict[str, Any]]:
        """Fetch every pick of a draft, raw.

        Each record carries ``pick_no``, ``round``, ``draft_slot``, ``roster_id``,
        ``player_id`` and ``metadata.amount`` (a string). Parsing lives in
        ``sleeper/draft.py``.
        """
        response = self._http.get(f"/draft/{draft_id}/picks")
        response.raise_for_status()
        return response.json()

    def get_transactions(self, league_id: str, week: int) -> list[dict[str, Any]]:
        """Fetch the executed transaction log for one week -- Sleeper's ``leg`` -- raw."""
        response = self._http.get(f"/league/{league_id}/transactions/{week}")
        response.raise_for_status()
        return response.json()
```

- [ ] **Step 6: Teach the shared fake client the three calls**

In `packages/league-automation/tests/sleeper/conftest.py`, import `SleeperDraft` and add to `FakeClient`:

```python
    def get_draft(self, draft_id: str) -> SleeperDraft:
        return SleeperDraft.model_validate(load_fixture("draft_2026.json"))

    def get_draft_picks(self, draft_id: str) -> list[dict]:
        return load_fixture("draft_picks_2026.json")

    def get_transactions(self, league_id: str, week: int) -> list[dict]:
        return load_fixture("transactions_2026_w1.json") if week == 1 else []
```

- [ ] **Step 7: Run the client tests and the whole sleeper suite**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper -v`
Expected: all pass (the fixture change is `extra="ignore"`-safe for every existing test).

- [ ] **Step 8: Commit**

```bash
git add packages/league-automation/tests/fixtures/sleeper packages/league-automation/src/ultimate_guillotine/sleeper/models.py packages/league-automation/src/ultimate_guillotine/sleeper/client.py packages/league-automation/tests/sleeper/test_client.py packages/league-automation/tests/sleeper/conftest.py
git commit -m "feat(sleeper): read the draft, its picks and the transaction log"
```

---

### Task 3: Shared coercions and the roster-to-team hop

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/values.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/teams.py`
- Create: `packages/league-automation/tests/sleeper/test_values.py`
- Create: `packages/league-automation/tests/sleeper/test_teams.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/scores.py:170-183`

**Interfaces:**
- Produces: `as_int(value: object) -> int | None`; `from_millis(value: object) -> datetime | None`; `teams_by_roster_id(conn, season_id: int) -> dict[int, int]`.

- [ ] **Step 1: Write the failing tests**

`packages/league-automation/tests/sleeper/test_values.py`:

```python
"""The two coercions every Sleeper payload needs: an int that may arrive as a string,
and a millisecond epoch that may be missing."""

from datetime import UTC, datetime

from ultimate_guillotine.sleeper.values import as_int, from_millis


def test_an_int_is_read_from_an_int_a_float_or_a_numeric_string() -> None:
    assert as_int(53) == 53
    assert as_int(53.0) == 53
    assert as_int("53") == 53


def test_a_bool_a_word_and_nothing_are_not_ints() -> None:
    """`True` is an int to Python and never to Sleeper; a bool must not read as 1."""
    assert as_int(True) is None
    assert as_int("fifty") is None
    assert as_int(None) is None
    assert as_int([53]) is None


def test_a_millisecond_epoch_becomes_an_aware_utc_datetime() -> None:
    assert from_millis(1788822090433) == datetime(2026, 9, 7, 4, 21, 30, 433000, tzinfo=UTC)


def test_a_missing_or_unusable_epoch_is_none() -> None:
    assert from_millis(None) is None
    assert from_millis("1788822090433") is None
    assert from_millis(True) is None
```

`packages/league-automation/tests/sleeper/test_teams.py`:

```python
"""The one hop from Sleeper's roster ids to this data layer's team ids, read from the
table rather than from the league payload so every sync attaches rows to the same team."""

from ultimate_guillotine.sleeper.teams import teams_by_roster_id


def test_the_hop_is_read_from_the_teams_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        season_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.members (display_name) values ('hop-fixture') returning id"
        )
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values (%s, %s, 'u-hop', 907, 'T') returning id",
            (season_id, member_id),
        )
        team_id = cur.fetchone()[0]
    assert teams_by_roster_id(conn, season_id) == {907: team_id}


def test_a_season_with_no_teams_is_an_empty_map(conn) -> None:
    assert teams_by_roster_id(conn, -1) == {}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_values.py packages/league-automation/tests/sleeper/test_teams.py -v`
Expected: `ModuleNotFoundError` for both modules.

- [ ] **Step 3: Write the two modules**

`packages/league-automation/src/ultimate_guillotine/sleeper/values.py`:

```python
"""Two coercions every Sleeper payload needs.

Sleeper sends integers as strings in some places (``metadata.amount`` on a pick,
every season field) and as numbers in others, and stamps time as a millisecond
epoch that may be null. Both readings live here once so the draft and
transaction loaders agree on what a bad value is.
"""

from datetime import UTC, datetime


def as_int(value: object) -> int | None:
    """``53``, ``53.0`` and ``"53"`` all read as 53; a bool, a word, or nothing is None.

    A bool is excluded first because ``True`` is an ``int`` to Python and never one to
    Sleeper: a flag must not silently read as an amount of 1.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def from_millis(value: object) -> datetime | None:
    """A millisecond epoch as an aware UTC datetime; anything that is not a number is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)
```

`packages/league-automation/src/ultimate_guillotine/sleeper/teams.py`:

```python
"""The one hop from Sleeper's roster ids to this data layer's team ids."""

import psycopg


def teams_by_roster_id(conn: psycopg.Connection, season_id: int) -> dict[int, int]:
    """``sleeper_roster_id`` -> ``teams.id`` for one season.

    Sleeper's feeds know rosters; every other table in this data layer knows teams.
    The hop is read from the database rather than from a league payload so a
    score, a pick, or a move can never be attached to a team the rest of the
    season's rows do not agree on. Runs on the caller's connection, inside the
    caller's transaction.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_roster_id, id from public.teams where season_id = %s",
            (season_id,),
        )
        return {roster_id: team_id for roster_id, team_id in cur.fetchall()}
```

- [ ] **Step 4: Make the score repository delegate**

In `packages/league-automation/src/ultimate_guillotine/sleeper/scores.py`, add `from ultimate_guillotine.sleeper.teams import teams_by_roster_id` to the imports and replace the body of `ScoreRepository.teams_by_roster_id` (keep its docstring's first line, drop the rest):

```python
    def teams_by_roster_id(self, season_id: int) -> dict[int, int]:
        """``sleeper_roster_id`` -> ``teams.id`` for one season; see ``sleeper/teams.py``."""
        return teams_by_roster_id(self._conn, season_id)
```

- [ ] **Step 5: Run the tests**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_values.py packages/league-automation/tests/sleeper/test_teams.py packages/league-automation/tests/sleeper/test_scores.py -v`
Expected: PASS, including the existing `test_the_roster_lookup_is_read_from_the_teams_table`.

- [ ] **Step 6: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/values.py packages/league-automation/src/ultimate_guillotine/sleeper/teams.py packages/league-automation/src/ultimate_guillotine/sleeper/scores.py packages/league-automation/tests/sleeper/test_values.py packages/league-automation/tests/sleeper/test_teams.py
git commit -m "refactor(sleeper): one roster-to-team hop and two shared coercions"
```

---

### Task 4: The draft loader and sync

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/draft.py`
- Create: `packages/league-automation/tests/sleeper/test_draft.py`

**Interfaces:**
- Consumes: `SleeperDraft`, `SleeperClient.get_league/get_draft/get_draft_picks`, `as_int`, `teams_by_roster_id`.
- Produces: `DraftPick(team_id, sleeper_player_id, sleeper_draft_id, pick_no, round, draft_slot, position, amount)`; `DraftReport(picks: int, status: str)` with `.skipped`; `load_draft_picks(draft, payload, team_by_roster_id) -> list[DraftPick]`; `DraftRepository(conn).upsert_many(season_id, picks, drafted_at, now) -> int`; `sync_draft(client, conn, league_id, season_id, now) -> DraftReport`.

- [ ] **Step 1: Write the failing pure tests**

`packages/league-automation/tests/sleeper/test_draft.py`:

```python
"""What `sleeper/draft.py` reads off the picks payload, and what it writes.

The parsing cases are pure. The sync cases run against the real table, because the
value of the upsert is the `(season_id, sleeper_player_id)` conflict target the daily
rerun depends on.
"""

from datetime import UTC, datetime

import pytest

from ultimate_guillotine.sleeper.draft import (
    DraftReport,
    load_draft_picks,
    sync_draft,
)
from ultimate_guillotine.sleeper.models import SleeperDraft, SleeperLeague
from ultimate_guillotine.sleeper.sync import sync_season

from .conftest import LEAGUE_ID, FakeClient, load_fixture

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

DRAFT = SleeperDraft.model_validate(
    {
        "draft_id": "d-1",
        "type": "auction",
        "status": "complete",
        "start_time": 1788822090433,
        "settings": {"teams": 2, "rounds": 2},
    }
)


def _pick(pick_no: int, roster_id: int, player_id: str, amount: object, **overrides) -> dict:
    record = {
        "draft_id": "d-1",
        "pick_no": pick_no,
        "round": 1 if pick_no <= 2 else 2,
        "draft_slot": roster_id,
        "roster_id": roster_id,
        "player_id": player_id,
        "picked_by": f"user-{roster_id:02d}",
        "metadata": {"amount": amount, "position": "RB", "player_id": player_id},
    }
    record.update(overrides)
    return record


PAYLOAD = [
    _pick(1, 1, "p1", "53"),
    _pick(2, 2, "p2", "1"),
    _pick(3, 1, "p3", "12"),
    _pick(4, 2, "p4", 7),
]
TEAMS = {1: 11, 2: 22}


def test_a_pick_is_mapped_onto_its_team_with_the_amount_as_an_int() -> None:
    picks = load_draft_picks(DRAFT, PAYLOAD, TEAMS)
    assert [(p.team_id, p.sleeper_player_id, p.amount) for p in picks] == [
        (11, "p1", 53),
        (22, "p2", 1),
        (11, "p3", 12),
        (22, "p4", 7),
    ]
    assert picks[0].sleeper_draft_id == "d-1"
    assert (picks[0].pick_no, picks[0].round, picks[0].draft_slot) == (1, 1, 1)
    assert picks[0].position == "RB"


def test_a_pick_without_a_position_keeps_none() -> None:
    picks = load_draft_picks(
        DRAFT, [_pick(1, 1, "p1", "53", metadata={"amount": "53"})] + PAYLOAD[1:], TEAMS
    )
    assert picks[0].position is None


def test_an_empty_payload_is_refused() -> None:
    with pytest.raises(ValueError, match="no picks"):
        load_draft_picks(DRAFT, [], TEAMS)


def test_fewer_picks_than_teams_times_rounds_is_refused() -> None:
    """A complete two-team, two-round auction has four picks; three is a partial payload."""
    with pytest.raises(ValueError, match="3 picks, expected at least 4"):
        load_draft_picks(DRAFT, PAYLOAD[:3], TEAMS)


def test_a_pick_without_an_amount_is_refused() -> None:
    """An auction league: a pick with no price is a malformed payload, not a free player."""
    payload = [_pick(1, 1, "p1", None)] + PAYLOAD[1:]
    with pytest.raises(ValueError, match="pick 1 has no auction amount"):
        load_draft_picks(DRAFT, payload, TEAMS)


def test_an_amount_below_one_is_refused() -> None:
    payload = [_pick(1, 1, "p1", "0")] + PAYLOAD[1:]
    with pytest.raises(ValueError, match="pick 1 has no auction amount"):
        load_draft_picks(DRAFT, payload, TEAMS)


def test_a_roster_with_no_team_row_is_refused() -> None:
    """The draft is a fixed fact about eighteen rosters; a missing one means the roster
    sync has not run, and writing the other seventeen would publish a draft with a hole."""
    with pytest.raises(ValueError, match="roster 2 has no team row"):
        load_draft_picks(DRAFT, PAYLOAD, {1: 11})


def test_a_malformed_pick_is_refused() -> None:
    payload = [_pick(1, 1, "p1", "53", player_id=None)] + PAYLOAD[1:]
    with pytest.raises(ValueError, match="pick 1 is malformed"):
        load_draft_picks(DRAFT, payload, TEAMS)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_draft.py -v`
Expected: `ModuleNotFoundError: ultimate_guillotine.sleeper.draft`.

- [ ] **Step 3: Write the loader**

`packages/league-automation/src/ultimate_guillotine/sleeper/draft.py`:

```python
"""The auction, from Sleeper's draft feed into ``public.draft_picks``.

Spec: docs/superpowers/specs/2026-09-10-player-card-design.md. The feed is
``/draft/{id}/picks``: one record per pick with ``pick_no``, ``round``,
``draft_slot``, ``roster_id``, ``player_id`` and ``metadata.amount`` as a string.
The draft record itself (``/draft/{id}``) says whether the auction is over and how
big it was, which is what the guards below check the payload against.

Shaped like ``scores.py``: fetch first, parse with a pure loader, upsert on a
natural key inside the transaction ``run_scheduled`` already holds. Unlike the
scores, a rerun writes the same rows -- the draft is a fact, not a live number --
so the daily fire exists only so a pick Sleeper corrects reaches the board without
anyone remembering.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.models import SleeperDraft
from ultimate_guillotine.sleeper.teams import teams_by_roster_id
from ultimate_guillotine.sleeper.values import as_int


@dataclass(frozen=True)
class DraftPick:
    """One auction pick, already mapped off Sleeper's roster id onto a team id."""

    team_id: int
    sleeper_player_id: str
    sleeper_draft_id: str
    pick_no: int
    round: int
    draft_slot: int
    #: The position Sleeper recorded on the pick -- what the auction ranked by.
    position: str | None
    amount: int


@dataclass(frozen=True)
class DraftReport:
    """What one ``ug sleeper draft`` run wrote. Counts only, never a name."""

    picks: int
    #: The draft's Sleeper status. Anything but ``complete`` means nothing was written.
    status: str

    @property
    def skipped(self) -> bool:
        return self.status != "complete"


def _amount(record: dict[str, Any]) -> int | None:
    """The auction price, or None when the pick carries no usable one.

    Sleeper sends it as a string inside ``metadata``. Zero is not a price: an
    auction pick costs at least a dollar, so ``"0"`` reads as missing.
    """
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    amount = as_int(metadata.get("amount"))
    return amount if amount is not None and amount >= 1 else None


def load_draft_picks(
    draft: SleeperDraft,
    payload: list[dict[str, Any]],
    team_by_roster_id: dict[int, int],
) -> list[DraftPick]:
    """Parse the picks payload into rows, or refuse it.

    Every guard raises rather than skipping. A partial auction on the board would
    look exactly like a finished one, and the mark beside a player's name would be
    silently wrong for everyone the payload dropped -- so the run fails, the last
    good rows stand, and the ops note says why.
    """
    if not payload:
        raise ValueError(f"sleeper returned no picks for draft {draft.draft_id}")
    expected = (draft.teams or 0) * (draft.rounds or 0)
    if len(payload) < expected:
        raise ValueError(
            f"draft {draft.draft_id}: {len(payload)} picks, expected at least {expected}"
        )
    picks: list[DraftPick] = []
    for record in payload:
        if not isinstance(record, dict):
            raise ValueError(f"draft {draft.draft_id}: a pick is not an object")
        pick_no = as_int(record.get("pick_no"))
        round_no = as_int(record.get("round"))
        slot = as_int(record.get("draft_slot"))
        roster_id = as_int(record.get("roster_id"))
        player_id = record.get("player_id")
        if (
            pick_no is None
            or round_no is None
            or slot is None
            or roster_id is None
            or not isinstance(player_id, str)
            or not player_id
        ):
            raise ValueError(
                f"draft {draft.draft_id}: pick {record.get('pick_no')} is malformed"
            )
        amount = _amount(record)
        if amount is None:
            raise ValueError(f"draft {draft.draft_id}: pick {pick_no} has no auction amount")
        team_id = team_by_roster_id.get(roster_id)
        if team_id is None:
            raise ValueError(
                f"draft {draft.draft_id}: roster {roster_id} has no team row; "
                f"run ug sleeper sync"
            )
        metadata = record.get("metadata")
        position = metadata.get("position") if isinstance(metadata, dict) else None
        picks.append(
            DraftPick(
                team_id=team_id,
                sleeper_player_id=player_id,
                sleeper_draft_id=draft.draft_id,
                pick_no=pick_no,
                round=round_no,
                draft_slot=slot,
                position=position if isinstance(position, str) and position else None,
                amount=amount,
            )
        )
    return picks


class DraftRepository:
    """Writes for the season's auction. Runs on the caller's connection and transaction."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_many(
        self,
        season_id: int,
        picks: list[DraftPick],
        drafted_at: datetime,
        now: datetime,
    ) -> int:
        """Write one row per pick, keyed on ``(season_id, sleeper_player_id)``.

        A player is auctioned once a season, so that is the conflict target. The
        second unique key, ``(season_id, sleeper_draft_id, pick_no)``, is a guard
        rather than a target: a pick Sleeper reassigns to a different player would
        trip it and fail the run loudly, which is right -- nothing here may delete
        the stale row, so a human has to look.
        """
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.draft_picks
                  (season_id, team_id, sleeper_player_id, sleeper_draft_id, pick_no, round,
                   draft_slot, position, amount, drafted_at, synced_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, sleeper_player_id) do update set
                  team_id = excluded.team_id,
                  sleeper_draft_id = excluded.sleeper_draft_id,
                  pick_no = excluded.pick_no,
                  round = excluded.round,
                  draft_slot = excluded.draft_slot,
                  position = excluded.position,
                  amount = excluded.amount,
                  drafted_at = excluded.drafted_at,
                  synced_at = excluded.synced_at
                """,
                [
                    (
                        season_id,
                        pick.team_id,
                        pick.sleeper_player_id,
                        pick.sleeper_draft_id,
                        pick.pick_no,
                        pick.round,
                        pick.draft_slot,
                        pick.position,
                        pick.amount,
                        drafted_at,
                        now,
                    )
                    for pick in picks
                ],
            )
        return len(picks)


def sync_draft(
    client: SleeperClient,
    conn: psycopg.Connection,
    league_id: str,
    season_id: int,
    now: datetime,
) -> DraftReport:
    """Fetch the league's canonical draft and, once it is complete, write its picks.

    Three fetches before any write. A draft that is not ``complete`` is a no-op that
    reports ``skipped`` -- before the auction the job has nothing to say. The
    payload then has to pass ``load_draft_picks`` or the run fails with the last
    good rows untouched.
    """
    league = client.get_league(league_id)
    if not league.draft_id:
        raise ValueError(f"league {league_id} names no draft")
    draft = client.get_draft(league.draft_id)
    if draft.status != "complete":
        return DraftReport(picks=0, status=draft.status)
    drafted_at = draft.started_at
    if drafted_at is None:
        raise ValueError(f"draft {draft.draft_id} has no start time")
    payload = client.get_draft_picks(draft.draft_id)
    picks = load_draft_picks(draft, payload, teams_by_roster_id(conn, season_id))
    DraftRepository(conn).upsert_many(season_id, picks, drafted_at, now)
    return DraftReport(picks=len(picks), status=draft.status)
```

- [ ] **Step 4: Run the pure tests**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_draft.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing DB tests**

Append to `packages/league-automation/tests/sleeper/test_draft.py`:

```python
class IncompleteDraftClient(FakeClient):
    """The shared fake, with the draft still running."""

    def get_draft(self, draft_id: str) -> SleeperDraft:
        raw = dict(load_fixture("draft_2026.json"))
        raw["status"] = "drafting"
        return SleeperDraft.model_validate(raw)


class NoDraftClient(FakeClient):
    def get_league(self, league_id: str) -> SleeperLeague:
        raw = dict(load_fixture("league_2026.json"))
        raw.pop("draft_id", None)
        return SleeperLeague.model_validate(raw)


def _rows(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "select team_id, sleeper_player_id, sleeper_draft_id, pick_no, round, draft_slot, "
            "position, amount, drafted_at from public.draft_picks order by pick_no"
        )
        return cur.fetchall()


def test_a_sync_writes_every_pick_onto_the_team_that_made_it(conn, season_id, team_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    report = sync_draft(FakeClient(), conn, LEAGUE_ID, season_id, NOW)
    assert report == DraftReport(picks=162, status="complete")
    rows = _rows(conn)
    assert len(rows) == 162
    first = load_fixture("draft_picks_2026.json")[0]
    assert rows[0][:2] == (team_id(first["roster_id"]), first["player_id"])
    assert rows[0][7] == int(first["metadata"]["amount"])
    assert rows[0][8] == datetime(2026, 9, 7, 4, 21, 30, 433000, tzinfo=UTC)


def test_a_rerun_rewrites_the_same_rows_and_moves_only_the_stamp(conn, season_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    sync_draft(FakeClient(), conn, LEAGUE_ID, season_id, NOW)
    before = _rows(conn)
    later = datetime(2026, 9, 11, 6, 0, tzinfo=UTC)
    sync_draft(FakeClient(), conn, LEAGUE_ID, season_id, later)
    assert _rows(conn) == before
    with conn.cursor() as cur:
        cur.execute("select distinct synced_at from public.draft_picks")
        assert cur.fetchall() == [(later,)]


def test_a_draft_still_running_is_skipped_and_writes_nothing(conn, season_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    report = sync_draft(IncompleteDraftClient(), conn, LEAGUE_ID, season_id, NOW)
    assert report == DraftReport(picks=0, status="drafting")
    assert report.skipped
    assert _rows(conn) == []


def test_a_league_naming_no_draft_is_an_error(conn, season_id) -> None:
    with pytest.raises(ValueError, match="names no draft"):
        sync_draft(NoDraftClient(), conn, LEAGUE_ID, season_id, NOW)


def test_a_season_with_no_teams_refuses_before_writing(conn, season_id) -> None:
    """Nothing to map the rosters onto: `ug sleeper sync` has not run."""
    with pytest.raises(ValueError, match="roster 1 has no team row"):
        sync_draft(FakeClient(), conn, LEAGUE_ID, season_id, NOW)
    assert _rows(conn) == []
```

- [ ] **Step 6: Run the DB tests**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_draft.py -v`
Expected: PASS (the loader already exists; these verify the writes). If `test_a_season_with_no_teams_refuses_before_writing` reports roster 3 rather than 1, the fixture's first pick is on roster 3 — match the message to the fixture's first `roster_id`.

- [ ] **Step 7: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/draft.py packages/league-automation/tests/sleeper/test_draft.py
git commit -m "feat(sleeper): sync the auction into public.draft_picks"
```

---

### Task 5: The transactions loader and sync

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/transactions.py`
- Create: `packages/league-automation/tests/sleeper/test_transactions.py`

**Interfaces:**
- Consumes: `SleeperClient.get_transactions`, `as_int`, `from_millis`, `teams_by_roster_id`.
- Produces: `KINDS`; `FaabMove(amount, from_team_id, to_team_id)`; `Move(sleeper_player_id, team_id, action)`; `Transaction(sleeper_transaction_id, kind, week, occurred_at, team_ids, faab_moves, waiver_bid, raw, moves)`; `TransactionLoad(transactions, unknown_kinds: Counter, unmatched_rosters: int, malformed: int)`; `load_transactions(payload, team_by_roster_id) -> TransactionLoad`; `TransactionRepository(conn).upsert_many(season_id, transactions, now) -> tuple[int, int]`; `TransactionReport(transactions, moves, weeks, unknown_kinds, unmatched_rosters, malformed)`; `sync_transactions(client, conn, league_id, season_id, weeks, now) -> TransactionReport`.

- [ ] **Step 1: Write the failing pure tests**

`packages/league-automation/tests/sleeper/test_transactions.py`:

```python
"""What `sleeper/transactions.py` reads off the transaction log, and what it writes.

The parsing cases are pure. The sync cases run against the real tables, because the
value of the upsert is the `sleeper_transaction_id` conflict target the ten-minute
rerun depends on.
"""

from collections import Counter
from datetime import UTC, datetime

from ultimate_guillotine.sleeper.sync import sync_season
from ultimate_guillotine.sleeper.transactions import (
    FaabMove,
    Move,
    TransactionReport,
    load_transactions,
    sync_transactions,
)

from .conftest import LEAGUE_ID, FakeClient, load_fixture

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
TEAMS = {1: 11, 2: 22, 3: 33}

TRADE = {
    "transaction_id": "t-1",
    "type": "trade",
    "status": "complete",
    "created": 1788876037088,
    "status_updated": 1788876100000,
    "leg": 1,
    "roster_ids": [1, 2],
    "adds": {"pA": 2, "pB": 1},
    "drops": {"pA": 1, "pB": 2},
    "waiver_budget": [{"amount": 65, "sender": 1, "receiver": 2}],
    "draft_picks": [],
    "settings": None,
}
CLAIM = {
    "transaction_id": "t-2",
    "type": "waiver",
    "status": "complete",
    "created": 1789005344972,
    "status_updated": None,
    "leg": 2,
    "roster_ids": [3],
    "adds": {"pC": 3},
    "drops": {"pD": 3},
    "waiver_budget": [],
    "settings": {"waiver_bid": 12, "seq": 1},
}
FAILED_BID = {**CLAIM, "transaction_id": "t-3", "status": "failed"}
PICKUP = {
    "transaction_id": "t-4",
    "type": "free_agent",
    "status": "complete",
    "created": 1789100000000,
    "leg": 2,
    "roster_ids": [2],
    "adds": {"pE": 2},
    "drops": None,
    "waiver_budget": None,
}


def test_a_trade_yields_an_add_for_the_receiver_and_a_drop_for_the_sender() -> None:
    load = load_transactions([TRADE], TEAMS)
    (tx,) = load.transactions
    assert tx.sleeper_transaction_id == "t-1"
    assert tx.kind == "trade"
    assert tx.team_ids == [11, 22]
    assert sorted(tx.moves, key=lambda m: (m.sleeper_player_id, m.action)) == [
        Move("pA", 22, "add"),
        Move("pA", 11, "drop"),
        Move("pB", 11, "add"),
        Move("pB", 22, "drop"),
    ]


def test_faab_moves_map_roster_ids_onto_team_ids() -> None:
    (tx,) = load_transactions([TRADE], TEAMS).transactions
    assert tx.faab_moves == [FaabMove(65, 11, 22)]
    assert tx.waiver_bid is None


def test_the_week_is_sleepers_leg_and_the_time_prefers_status_updated() -> None:
    (tx,) = load_transactions([TRADE], TEAMS).transactions
    assert tx.week == 1
    assert tx.occurred_at == datetime(2026, 9, 7, 19, 21, 40, tzinfo=UTC)


def test_a_claim_keeps_its_bid_and_falls_back_to_created() -> None:
    (tx,) = load_transactions([CLAIM], TEAMS).transactions
    assert tx.kind == "waiver"
    assert tx.waiver_bid == 12
    assert tx.occurred_at == datetime(2026, 9, 9, 7, 15, 44, 972000, tzinfo=UTC)
    assert sorted(tx.moves, key=lambda m: m.action) == [
        Move("pC", 33, "add"),
        Move("pD", 33, "drop"),
    ]


def test_a_failed_bid_is_not_a_transaction() -> None:
    load = load_transactions([FAILED_BID], TEAMS)
    assert load.transactions == []
    assert (load.unknown_kinds, load.unmatched_rosters, load.malformed) == (Counter(), 0, 0)


def test_null_drops_and_null_faab_read_as_none_of_either() -> None:
    (tx,) = load_transactions([PICKUP], TEAMS).transactions
    assert tx.moves == [Move("pE", 22, "add")]
    assert tx.faab_moves == []
    assert tx.waiver_bid is None


def test_the_raw_record_is_kept_verbatim() -> None:
    (tx,) = load_transactions([TRADE], TEAMS).transactions
    assert tx.raw == TRADE


def test_an_unknown_kind_is_counted_and_skipped() -> None:
    """One new string from Sleeper must not stall the whole log."""
    load = load_transactions([{**TRADE, "type": "gift"}, PICKUP], TEAMS)
    assert [t.sleeper_transaction_id for t in load.transactions] == ["t-4"]
    assert load.unknown_kinds == Counter({"gift": 1})


def test_a_roster_with_no_team_row_is_counted_and_skipped() -> None:
    load = load_transactions([TRADE, PICKUP], {2: 22})
    assert [t.sleeper_transaction_id for t in load.transactions] == ["t-4"]
    assert load.unmatched_rosters == 1


def test_a_record_missing_its_id_week_or_time_is_malformed() -> None:
    load = load_transactions(
        [
            {**TRADE, "transaction_id": None},
            {**TRADE, "leg": None},
            {**TRADE, "created": None, "status_updated": None},
            "not a record",
        ],
        TEAMS,
    )
    assert load.transactions == []
    assert load.malformed == 4
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_transactions.py -v`
Expected: `ModuleNotFoundError: ultimate_guillotine.sleeper.transactions`.

- [ ] **Step 3: Write the loader, repository, and sync**

`packages/league-automation/src/ultimate_guillotine/sleeper/transactions.py`:

```python
"""The executed transaction log, from Sleeper into ``public.transactions`` and
``public.transaction_moves``.

Spec: docs/superpowers/specs/2026-09-10-player-card-design.md. The feed is
``/league/{id}/transactions/{week}``, one record per transaction of that leg:
``type`` (trade, waiver, free_agent, commissioner), ``status``, ``created`` and
``status_updated`` as millisecond epochs, ``leg``, ``roster_ids``, ``adds`` and
``drops`` as ``{player_id: roster_id}`` maps (``adds`` is the receiving roster,
``drops`` the sending one), ``waiver_budget`` as ``{amount, sender, receiver}``
roster transfers, and ``settings.waiver_bid`` on a claim.

Only completed records are kept: a failed waiver bid says nothing about a
player's journey, and 2025 had 1,269 of them. An unknown ``type`` and a roster
with no team row are counted and skipped rather than failing the run -- one new
string from Sleeper must not stall the log -- on the players sync's reasoning.

Shaped like ``scores.py``: fetch every week first, parse with a pure loader,
upsert on ``sleeper_transaction_id`` inside the transaction ``run_scheduled``
already holds. Nothing is deleted; a rerun rewrites the same rows.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.teams import teams_by_roster_id
from ultimate_guillotine.sleeper.values import as_int, from_millis

#: The four kinds Sleeper's log carries and the column's check constraint admits.
KINDS = frozenset({"trade", "waiver", "free_agent", "commissioner"})


@dataclass(frozen=True)
class FaabMove:
    amount: int
    from_team_id: int
    to_team_id: int


@dataclass(frozen=True)
class Move:
    """One player on one side of a transaction: added to a team, or dropped by one."""

    sleeper_player_id: str
    team_id: int
    action: str


@dataclass(frozen=True)
class Transaction:
    """One completed transaction, mapped off roster ids onto team ids."""

    sleeper_transaction_id: str
    kind: str
    #: Sleeper's ``leg``: the week the transaction was processed in, never the clock.
    week: int
    occurred_at: datetime
    team_ids: list[int]
    faab_moves: list[FaabMove]
    waiver_bid: int | None
    raw: dict[str, Any]
    moves: list[Move]


@dataclass(frozen=True)
class TransactionLoad:
    """The transactions a payload yielded, and what could not be read off it."""

    transactions: list[Transaction]
    unknown_kinds: Counter[str] = field(default_factory=Counter)
    unmatched_rosters: int = 0
    malformed: int = 0


@dataclass(frozen=True)
class TransactionReport:
    """What one ``ug sleeper transactions`` run wrote. Counts only, never a name."""

    transactions: int
    moves: int
    weeks: list[int]
    unknown_kinds: Counter[str] = field(default_factory=Counter)
    unmatched_rosters: int = 0
    malformed: int = 0


def _team_map(value: object, team_by_roster_id: dict[int, int]) -> dict[str, int] | None:
    """An ``adds``/``drops`` map as player id -> team id; None when a roster is unknown."""
    if value is None or not isinstance(value, dict):
        return {}
    mapped: dict[str, int] = {}
    for player_id, roster_id in value.items():
        team_id = team_by_roster_id.get(as_int(roster_id))  # type: ignore[arg-type]
        if team_id is None:
            return None
        mapped[str(player_id)] = team_id
    return mapped


def _faab_moves(value: object, team_by_roster_id: dict[int, int]) -> list[FaabMove] | None:
    if value is None or not isinstance(value, list):
        return []
    moves: list[FaabMove] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        amount = as_int(entry.get("amount"))
        sender = team_by_roster_id.get(as_int(entry.get("sender")))  # type: ignore[arg-type]
        receiver = team_by_roster_id.get(as_int(entry.get("receiver")))  # type: ignore[arg-type]
        if amount is None:
            continue
        if sender is None or receiver is None:
            return None
        moves.append(FaabMove(amount, sender, receiver))
    return moves


def _team_ids(value: object, team_by_roster_id: dict[int, int]) -> list[int] | None:
    if not isinstance(value, list):
        return []
    team_ids: list[int] = []
    for roster_id in value:
        team_id = team_by_roster_id.get(as_int(roster_id))  # type: ignore[arg-type]
        if team_id is None:
            return None
        team_ids.append(team_id)
    return team_ids


def load_transactions(
    payload: list[dict[str, Any]], team_by_roster_id: dict[int, int]
) -> TransactionLoad:
    """Parse one week's log into rows, counting what was skipped and why."""
    transactions: list[Transaction] = []
    unknown: Counter[str] = Counter()
    unmatched = 0
    malformed = 0
    for record in payload:
        if not isinstance(record, dict):
            malformed += 1
            continue
        if record.get("status") != "complete":
            continue
        kind = record.get("type")
        if kind not in KINDS:
            unknown[str(kind)] += 1
            continue
        transaction_id = record.get("transaction_id")
        week = as_int(record.get("leg"))
        occurred_at = from_millis(record.get("status_updated")) or from_millis(
            record.get("created")
        )
        if (
            not isinstance(transaction_id, str)
            or not transaction_id
            or week is None
            or occurred_at is None
        ):
            malformed += 1
            continue
        team_ids = _team_ids(record.get("roster_ids"), team_by_roster_id)
        adds = _team_map(record.get("adds"), team_by_roster_id)
        drops = _team_map(record.get("drops"), team_by_roster_id)
        faab = _faab_moves(record.get("waiver_budget"), team_by_roster_id)
        if team_ids is None or adds is None or drops is None or faab is None:
            unmatched += 1
            continue
        settings = record.get("settings")
        bid = None
        if kind == "waiver" and isinstance(settings, dict):
            bid = as_int(settings.get("waiver_bid"))
        moves = [Move(pid, tid, "add") for pid, tid in adds.items()]
        moves += [Move(pid, tid, "drop") for pid, tid in drops.items()]
        transactions.append(
            Transaction(
                sleeper_transaction_id=transaction_id,
                kind=kind,
                week=week,
                occurred_at=occurred_at,
                team_ids=team_ids,
                faab_moves=faab,
                waiver_bid=bid,
                raw=dict(record),
                moves=moves,
            )
        )
    return TransactionLoad(transactions, unknown, unmatched, malformed)


class TransactionRepository:
    """Writes for the transaction log. Runs on the caller's connection and transaction."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_many(
        self, season_id: int, transactions: list[Transaction], now: datetime
    ) -> tuple[int, int]:
        """Write each transaction and its moves; returns ``(transactions, moves)`` written.

        The transaction row upserts on ``sleeper_transaction_id`` and returns its id,
        which the moves then key on. A move upserts on
        ``(transaction_id, sleeper_player_id, action)``. A move Sleeper later removes
        from a record would be left standing -- nothing here deletes -- which the raw
        column makes visible and which has never been observed.
        """
        moves_written = 0
        with self._conn.cursor() as cur:
            for tx in transactions:
                cur.execute(
                    """
                    insert into public.transactions
                      (season_id, sleeper_transaction_id, kind, week, occurred_at, team_ids,
                       faab_moves, waiver_bid, raw, synced_at)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (sleeper_transaction_id) do update set
                      kind = excluded.kind,
                      week = excluded.week,
                      occurred_at = excluded.occurred_at,
                      team_ids = excluded.team_ids,
                      faab_moves = excluded.faab_moves,
                      waiver_bid = excluded.waiver_bid,
                      raw = excluded.raw,
                      synced_at = excluded.synced_at
                    returning id
                    """,
                    (
                        season_id,
                        tx.sleeper_transaction_id,
                        tx.kind,
                        tx.week,
                        tx.occurred_at,
                        tx.team_ids,
                        Jsonb(
                            [
                                {
                                    "amount": m.amount,
                                    "from_team_id": m.from_team_id,
                                    "to_team_id": m.to_team_id,
                                }
                                for m in tx.faab_moves
                            ]
                        ),
                        tx.waiver_bid,
                        Jsonb(tx.raw),
                        now,
                    ),
                )
                transaction_id = cur.fetchone()[0]
                if tx.moves:
                    cur.executemany(
                        """
                        insert into public.transaction_moves
                          (transaction_id, season_id, sleeper_player_id, team_id, action)
                        values (%s, %s, %s, %s, %s)
                        on conflict (transaction_id, sleeper_player_id, action) do update set
                          team_id = excluded.team_id
                        """,
                        [
                            (transaction_id, season_id, m.sleeper_player_id, m.team_id, m.action)
                            for m in tx.moves
                        ],
                    )
                    moves_written += len(tx.moves)
        return len(transactions), moves_written


def sync_transactions(
    client: SleeperClient,
    conn: psycopg.Connection,
    league_id: str,
    season_id: int,
    weeks: Sequence[int],
    now: datetime,
) -> TransactionReport:
    """Fetch the given weeks' logs, then upsert every completed transaction and its moves.

    Every week is fetched before anything is written, so a failing week aborts the
    run with the last good rows untouched. An empty week is normal -- a quiet
    Tuesday -- and writes nothing; the one refusal is a season with no teams to map
    onto, which is ``ug sleeper sync`` not having run.
    """
    team_map = teams_by_roster_id(conn, season_id)
    if not team_map:
        raise ValueError("no teams for the season; run ug sleeper sync first")
    payloads: list[tuple[int, list[dict[str, Any]]]] = []
    for week in weeks:
        payload = client.get_transactions(league_id, week)
        if not isinstance(payload, list):
            raise ValueError(f"sleeper returned no transaction list for week {week}")
        payloads.append((week, payload))
    repo = TransactionRepository(conn)
    unknown: Counter[str] = Counter()
    unmatched = malformed = written = moves = 0
    for _week, payload in payloads:
        load = load_transactions(payload, team_map)
        unknown.update(load.unknown_kinds)
        unmatched += load.unmatched_rosters
        malformed += load.malformed
        wrote, moved = repo.upsert_many(season_id, load.transactions, now)
        written += wrote
        moves += moved
    return TransactionReport(
        transactions=written,
        moves=moves,
        weeks=list(weeks),
        unknown_kinds=unknown,
        unmatched_rosters=unmatched,
        malformed=malformed,
    )
```

- [ ] **Step 4: Run the pure tests**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_transactions.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing DB tests**

Append to `packages/league-automation/tests/sleeper/test_transactions.py`:

```python
class RecordingClient(FakeClient):
    """The shared fake, remembering which weeks were asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.weeks: list[int] = []

    def get_transactions(self, league_id: str, week: int) -> list[dict]:
        self.weeks.append(week)
        return super().get_transactions(league_id, week)


def _fixture_moves() -> int:
    return sum(
        len(t.get("adds") or {}) + len(t.get("drops") or {})
        for t in load_fixture("transactions_2026_w1.json")
        if t["status"] == "complete"
    )


def _rows(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_transaction_id, kind, week, occurred_at, team_ids, faab_moves, "
            "waiver_bid from public.transactions order by sleeper_transaction_id"
        )
        return cur.fetchall()


def test_a_sync_writes_the_week_and_its_moves(conn, season_id, team_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    client = RecordingClient()
    report = sync_transactions(client, conn, LEAGUE_ID, season_id, [1], NOW)
    assert report == TransactionReport(transactions=8, moves=_fixture_moves(), weeks=[1])
    assert client.weeks == [1]
    rows = _rows(conn)
    assert len(rows) == 8
    trade = next(r for r in rows if r[0] == "1403051427646935040")
    assert trade[1:3] == ("trade", 1)
    assert set(trade[4]) == {team_id(1), team_id(16)}
    assert trade[5] == [{"amount": 65, "from_team_id": team_id(1), "to_team_id": team_id(16)}]
    with conn.cursor() as cur:
        cur.execute(
            "select m.sleeper_player_id, m.team_id, m.action from public.transaction_moves m "
            "join public.transactions t on t.id = m.transaction_id "
            "where t.sleeper_transaction_id = %s order by 1, 3",
            ("1403051427646935040",),
        )
        assert cur.fetchall() == [
            ("12534", team_id(16), "add"),
            ("12534", team_id(1), "drop"),
            ("9487", team_id(1), "add"),
            ("9487", team_id(16), "drop"),
        ]


def test_a_rerun_rewrites_the_same_rows_and_moves_only_the_stamp(conn, season_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    sync_transactions(FakeClient(), conn, LEAGUE_ID, season_id, [1], NOW)
    before = _rows(conn)
    later = datetime(2026, 9, 10, 12, 10, tzinfo=UTC)
    sync_transactions(FakeClient(), conn, LEAGUE_ID, season_id, [1], later)
    assert _rows(conn) == before
    with conn.cursor() as cur:
        cur.execute("select distinct synced_at from public.transactions")
        assert cur.fetchall() == [(later,)]
        cur.execute("select count(*) from public.transaction_moves")
        assert cur.fetchone()[0] == _fixture_moves()


def test_an_empty_week_writes_nothing_and_is_not_a_failure(conn, season_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    client = RecordingClient()
    report = sync_transactions(client, conn, LEAGUE_ID, season_id, [1, 2], NOW)
    assert client.weeks == [1, 2]
    assert (report.transactions, report.weeks) == (8, [1, 2])


def test_a_season_with_no_teams_refuses_before_fetching(conn, season_id) -> None:
    client = RecordingClient()
    try:
        sync_transactions(client, conn, LEAGUE_ID, season_id, [1], NOW)
    except ValueError as exc:
        assert "run ug sleeper sync" in str(exc)
    else:  # pragma: no cover - the assertion is the point
        raise AssertionError("expected a refusal")
    assert client.weeks == []
```

- [ ] **Step 6: Run the DB tests**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_transactions.py -v`
Expected: PASS. The trade `1403051427646935040` is the Supreme Projections ↔ Rick Vice deal; rosters 1 and 16 swap players `12534` and `9487` with $65 FAAB moving from roster 1 to roster 16 — confirm the ids against the fixture if an assertion disagrees.

- [ ] **Step 7: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper/transactions.py packages/league-automation/tests/sleeper/test_transactions.py
git commit -m "feat(sleeper): sync the executed transaction log and its per-player moves"
```

---

### Task 6: `ug sleeper draft`

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`
- Create: `packages/league-automation/tests/cli/test_sleeper_draft.py`

**Interfaces:**
- Consumes: `sync_draft`, `DraftReport`, `_season_id`, `SYNC_YEAR`, `run_scheduled_with_notes`.
- Produces: `cmd_draft(args) -> int`, agent `draft-sync`, subcommand `ug sleeper draft [--quiet]`.

- [ ] **Step 1: Write the failing tests**

`packages/league-automation/tests/cli/test_sleeper_draft.py`:

```python
"""What `ug sleeper draft` does around the sync it wraps: the season it looks up, the
agent it records under, and the counts-only line it prints."""

import argparse
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import sleeper as sleeper_cli
from ultimate_guillotine.sleeper.draft import DraftReport

from .test_sleeper_scores import FakeConn, FakeNotifier


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: FakeConn,
    report: DraftReport,
    agents: list[str] | None = None,
) -> list[tuple[str, int]]:
    notifier = FakeNotifier()
    monkeypatch.setattr(
        sleeper_cli,
        "build_deps",
        lambda: SimpleNamespace(
            conn=conn, notifier=notifier, settings=SimpleNamespace(sleeper_league_id="league-1")
        ),
    )
    monkeypatch.setattr(sleeper_cli.httpx, "Client", lambda: object())
    monkeypatch.setattr(sleeper_cli, "SleeperClient", lambda http: object())
    calls: list[tuple[str, int]] = []

    def fake_sync(client, target, league_id, season_id, now):
        calls.append((league_id, season_id))
        return report

    monkeypatch.setattr(sleeper_cli, "sync_draft", fake_sync)

    def fake_runner(deps, agent, now, action):
        if agents is not None:
            agents.append(agent)
        return action(1)

    monkeypatch.setattr(sleeper_cli, "run_scheduled_with_notes", fake_runner)
    return calls


def test_draft_help_exists() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "sleeper", "draft", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--quiet" in result.stdout


def test_the_season_is_the_leagues_own_year(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(season_row=(4,))
    calls = _wire(monkeypatch, conn=conn, report=DraftReport(picks=162, status="complete"))

    assert sleeper_cli.cmd_draft(argparse.Namespace(quiet=True)) == 0
    assert calls == [("league-1", 4)]
    assert conn.queries[0][1] == (sleeper_cli.SYNC_YEAR,)


def test_the_run_is_recorded_under_the_agent_the_cron_manifest_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents: list[str] = []
    _wire(
        monkeypatch,
        conn=FakeConn(),
        report=DraftReport(picks=162, status="complete"),
        agents=agents,
    )
    sleeper_cli.cmd_draft(argparse.Namespace(quiet=True))
    assert agents == ["draft-sync"]


def test_the_success_line_is_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), report=DraftReport(picks=162, status="complete"))
    sleeper_cli.cmd_draft(argparse.Namespace(quiet=False))
    assert capsys.readouterr().out == "draft: 162 picks\n"


def test_a_draft_still_running_says_so_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), report=DraftReport(picks=0, status="drafting"))
    assert sleeper_cli.cmd_draft(argparse.Namespace(quiet=False)) == 0
    assert capsys.readouterr().out == "draft: skipped, status=drafting\n"


def test_quiet_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), report=DraftReport(picks=0, status="drafting"))
    sleeper_cli.cmd_draft(argparse.Namespace(quiet=True))
    assert capsys.readouterr().out == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/cli/test_sleeper_draft.py -v`
Expected: `AttributeError: module ... has no attribute 'cmd_draft'` and the help test fails with `invalid choice: 'draft'`.

- [ ] **Step 3: Register the subcommand and write the handler**

In `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`, add the import:

```python
from ultimate_guillotine.sleeper.draft import sync_draft
```

In `register`, after the `scores_parser` block:

```python
    draft_parser = sleeper_sub.add_parser("draft", help="sync the auction results")
    draft_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    draft_parser.set_defaults(handler=cmd_draft)
```

Add the handler after `cmd_scores`:

```python
def cmd_draft(args: argparse.Namespace) -> int:
    """Sync the season's auction into `public.draft_picks`.

    The season is the league's own (`SYNC_YEAR`), not the year `nfl_state` reports:
    the auction belongs to the league season it opened, and a January run must not
    file it under the next NFL year. Before the auction is complete the sync reports
    `skipped` and the run stays green; afterwards it writes 162 rows a day whether or
    not they changed, so a pick Sleeper corrects reaches the board without anyone
    remembering to run this by hand.
    """
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        report = sync_draft(
            SleeperClient(httpx.Client()),
            conn,
            deps.settings.sleeper_league_id,
            _season_id(conn, SYNC_YEAR),
            now,
        )
        if not args.quiet:
            if report.skipped:
                print(f"draft: skipped, status={report.status}")
            else:
                print(f"draft: {report.picks} picks")
        return 0

    return run_scheduled_with_notes(deps, "draft-sync", now, action)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/cli/test_sleeper_draft.py packages/league-automation/tests/cli/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/cli/sleeper.py packages/league-automation/tests/cli/test_sleeper_draft.py
git commit -m "feat(cli): ug sleeper draft"
```

---

### Task 7: `ug sleeper transactions`

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`
- Create: `packages/league-automation/tests/cli/test_sleeper_transactions.py`

**Interfaces:**
- Consumes: `sync_transactions`, `TransactionReport`, `current_week`, `_season_id`, `post_ops`.
- Produces: `cmd_transactions(args) -> int`, agent `transactions-sync`, subcommand `ug sleeper transactions [--week N] [--all] [--quiet]`, and `weeks_to_sync(current: int, week: int | None, all_weeks: bool) -> list[int]`.

- [ ] **Step 1: Write the failing tests**

`packages/league-automation/tests/cli/test_sleeper_transactions.py`:

```python
"""What `ug sleeper transactions` does around the sync it wraps: which weeks it asks for,
the off-season no-op, the agent it records under, and the notes it posts."""

import argparse
import subprocess
import sys
from collections import Counter
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import sleeper as sleeper_cli
from ultimate_guillotine.sleeper.transactions import TransactionReport

from .test_sleeper_scores import FakeConn, FakeNotifier


def _report(weeks: list[int], **overrides) -> TransactionReport:
    return TransactionReport(
        **{"transactions": 8, "moves": 14, "weeks": weeks, **overrides}
    )


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: FakeConn,
    season_type: str = "regular",
    season: int = 2026,
    week: int = 3,
    report_overrides: dict | None = None,
    agents: list[str] | None = None,
) -> tuple[FakeNotifier, list[list[int]]]:
    notifier = FakeNotifier()
    monkeypatch.setattr(
        sleeper_cli,
        "build_deps",
        lambda: SimpleNamespace(
            conn=conn, notifier=notifier, settings=SimpleNamespace(sleeper_league_id="league-1")
        ),
    )
    monkeypatch.setattr(sleeper_cli.httpx, "Client", lambda: object())
    monkeypatch.setattr(sleeper_cli, "SleeperClient", lambda http: object())
    monkeypatch.setattr(
        sleeper_cli,
        "current_week",
        lambda client, conn, now: SimpleNamespace(
            season=season, season_type=season_type, week=week
        ),
    )
    asked: list[list[int]] = []

    def fake_sync(client, target, league_id, season_id, weeks, now):
        asked.append(list(weeks))
        return _report(list(weeks), **(report_overrides or {}))

    monkeypatch.setattr(sleeper_cli, "sync_transactions", fake_sync)

    def fake_runner(deps, agent, now, action):
        if agents is not None:
            agents.append(agent)
        return action(1)

    monkeypatch.setattr(sleeper_cli, "run_scheduled_with_notes", fake_runner)
    return notifier, asked


def _args(**overrides) -> argparse.Namespace:
    return argparse.Namespace(**{"week": None, "all": False, "quiet": True, **overrides})


def test_transactions_help_lists_week_and_all() -> None:
    result = subprocess.run(
        [
            sys.executable, "-m", "ultimate_guillotine.cli.main",
            "sleeper", "transactions", "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--week" in result.stdout
    assert "--all" in result.stdout


def test_the_default_is_the_previous_and_current_week() -> None:
    assert sleeper_cli.weeks_to_sync(3, None, False) == [2, 3]


def test_week_one_has_no_previous_week() -> None:
    assert sleeper_cli.weeks_to_sync(1, None, False) == [1]


def test_all_walks_from_week_one() -> None:
    assert sleeper_cli.weeks_to_sync(4, None, True) == [1, 2, 3, 4]


def test_an_explicit_week_is_just_that_week() -> None:
    assert sleeper_cli.weeks_to_sync(4, 2, False) == [2]


def test_the_weeks_asked_of_the_sync_follow_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _notifier, asked = _wire(monkeypatch, conn=FakeConn(), week=5)
    assert sleeper_cli.cmd_transactions(_args()) == 0
    assert asked == [[4, 5]]


def test_the_season_row_is_looked_up_by_the_state_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    _wire(monkeypatch, conn=conn, season=2027)
    sleeper_cli.cmd_transactions(_args())
    assert conn.queries[0][1] == (2027,)


def test_a_preseason_run_is_a_clean_no_op(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _notifier, asked = _wire(monkeypatch, conn=FakeConn(), season_type="pre")
    assert sleeper_cli.cmd_transactions(_args(quiet=False)) == 0
    assert asked == []
    assert capsys.readouterr().out == "transactions: skipped, season_type=pre\n"


def test_the_run_is_recorded_under_the_agent_the_cron_manifest_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents: list[str] = []
    _wire(monkeypatch, conn=FakeConn(), agents=agents)
    sleeper_cli.cmd_transactions(_args())
    assert agents == ["transactions-sync"]


def test_the_success_line_is_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), week=3)
    sleeper_cli.cmd_transactions(_args(quiet=False))
    assert capsys.readouterr().out == "transactions: 8 transactions, 14 moves, weeks 2-3\n"


def test_an_unknown_kind_posts_one_ops_note(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier, _asked = _wire(
        monkeypatch, conn=FakeConn(), report_overrides={"unknown_kinds": Counter({"gift": 2})}
    )
    assert sleeper_cli.cmd_transactions(_args()) == 0
    assert notifier.notes == [
        "transactions weeks 2-3: 2 record(s) of a kind this build does not know (gift); "
        "they are skipped until `KINDS` learns them"
    ]


def test_an_unmatched_roster_posts_one_ops_note(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier, _asked = _wire(
        monkeypatch, conn=FakeConn(), report_overrides={"unmatched_rosters": 1}
    )
    sleeper_cli.cmd_transactions(_args())
    assert notifier.notes == [
        "transactions weeks 2-3: 1 record(s) name a roster with no team row; "
        "run `ug sleeper sync`"
    ]


def test_a_clean_run_says_nothing_in_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier, _asked = _wire(monkeypatch, conn=FakeConn())
    sleeper_cli.cmd_transactions(_args())
    assert notifier.notes == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/cli/test_sleeper_transactions.py -v`
Expected: `AttributeError` on `weeks_to_sync` / `cmd_transactions`; the help test fails with `invalid choice: 'transactions'`.

- [ ] **Step 3: Register the subcommand, the week rule, and the handler**

In `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`, add the import:

```python
from ultimate_guillotine.sleeper.transactions import sync_transactions
```

In `register`, after the `draft_parser` block:

```python
    tx_parser = sleeper_sub.add_parser("transactions", help="sync the transaction log")
    tx_parser.add_argument("--week", type=int, default=None, help="one week to sync")
    tx_parser.add_argument(
        "--all", action="store_true", help="every week from 1 to the current one (backfill)"
    )
    tx_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    tx_parser.set_defaults(handler=cmd_transactions)
```

Add after `cmd_draft`:

```python
def weeks_to_sync(current: int, week: int | None, all_weeks: bool) -> list[int]:
    """Which weeks a transactions run asks Sleeper for.

    The default is the current week and the one before it, clamped to week 1: a deal
    processed late at a week boundary lands in the new leg, and the previous week
    covers the seam. `--all` walks the season for a backfill; `--week` is one week.
    """
    if week is not None:
        return [week]
    if all_weeks:
        return list(range(1, current + 1))
    return [w for w in (current - 1, current) if w >= 1]


def _weeks_label(weeks: list[int]) -> str:
    return f"{weeks[0]}-{weeks[-1]}" if len(weeks) > 1 else str(weeks[0])


def cmd_transactions(args: argparse.Namespace) -> int:
    """Sync the executed transaction log for the weeks `weeks_to_sync` picks.

    Shaped like `cmd_scores`: the week comes from `nfl_state`, the off-season is a
    no-op rather than a failure, and the run is recorded as `transactions-sync`.
    Two things can be worth a note without failing the run -- a record of a kind
    this build has never seen, and a roster no team row names -- and each posts once
    per run, on the players sync's reasoning that a new Sleeper string is something
    somebody has to look at, not an outage.
    """
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)
    client = SleeperClient(httpx.Client())

    def action(run_id: int) -> int:
        state = current_week(client, conn, now)
        if state.season_type != "regular":
            if not args.quiet:
                print(f"transactions: skipped, season_type={state.season_type}")
            return 0
        weeks = weeks_to_sync(state.week, args.week, args.all)
        report = sync_transactions(
            client,
            conn,
            deps.settings.sleeper_league_id,
            _season_id(conn, state.season),
            weeks,
            now,
        )
        label = _weeks_label(report.weeks)
        if not args.quiet:
            print(
                f"transactions: {report.transactions} transactions, {report.moves} moves, "
                f"weeks {label}"
            )
        if report.unknown_kinds:
            kinds = ", ".join(sorted(report.unknown_kinds))
            post_ops(
                deps.notifier,
                f"transactions weeks {label}: {sum(report.unknown_kinds.values())} record(s) "
                f"of a kind this build does not know ({kinds}); they are skipped until "
                f"`KINDS` learns them",
            )
        if report.unmatched_rosters:
            post_ops(
                deps.notifier,
                f"transactions weeks {label}: {report.unmatched_rosters} record(s) name a "
                f"roster with no team row; run `ug sleeper sync`",
            )
        return 0

    return run_scheduled_with_notes(deps, "transactions-sync", now, action)
```

- [ ] **Step 4: Run the CLI tests and lint**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/cli -v && pnpm lint:agents`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/cli/sleeper.py packages/league-automation/tests/cli/test_sleeper_transactions.py
git commit -m "feat(cli): ug sleeper transactions"
```

---

### Task 8: Cron manifest, script templates, runbook

**Files:**
- Create: `hermes/guillotine/scripts/guillotine_sleeper_draft.sh.template`
- Create: `hermes/guillotine/scripts/guillotine_sleeper_transactions.sh.template`
- Modify: `hermes/guillotine/cron.yaml`
- Modify: `packages/league-automation/tests/hermes/test_cron_manifest.py`
- Modify: `docs/runbooks/mac-mini.md`

- [ ] **Step 1: Write the failing manifest tests**

In `packages/league-automation/tests/hermes/test_cron_manifest.py`, extend the agent set in `test_the_scheduled_agents_are_the_ones_the_cli_records`:

```python
def test_the_scheduled_agents_are_the_ones_the_cli_records() -> None:
    assert {job["agent"] for job in JOBS} == {
        "health", "gap-fill", "sleeper-sync", "run-audit", "players-sync",
        "nfl-state", "projections-sync", "scores-sync", "draft-sync", "transactions-sync",
    }
```

Append:

```python
def test_the_player_card_jobs_are_pinned() -> None:
    """The auction is a fact that changes once a year, so once a day is plenty and the
    gap budget is the daily run-audit's. The transaction log moves any time a manager
    does, so it runs with the roster sync's cadence and speaks in the channel like it."""
    draft = next(j for j in JOBS if j["name"] == "guillotine-sleeper-draft")
    assert (draft["agent"], draft["schedule"], draft["deliver"]) == (
        "draft-sync", "0 6 * * *", "discord:#guillotine-ops",
    )
    assert int(draft["max_gap_minutes"]) > 24 * 60
    transactions = next(j for j in JOBS if j["name"] == "guillotine-sleeper-transactions")
    assert (transactions["agent"], transactions["schedule"], transactions["deliver"]) == (
        "transactions-sync", "every 10m", "discord:#guillotine-ops",
    )
    assert int(transactions["max_gap_minutes"]) >= 30
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/hermes/test_cron_manifest.py -v`
Expected: the agent-set test and the pin test fail; `test_every_job_points_at_a_script_template_that_exists` still passes.

- [ ] **Step 3: Add the two script templates**

`hermes/guillotine/scripts/guillotine_sleeper_draft.sh.template`:

```bash
#!/bin/bash
set -euo pipefail
cd "__REPO__"
exec /opt/homebrew/bin/uv run --project packages/league-automation ug sleeper draft --quiet
```

`hermes/guillotine/scripts/guillotine_sleeper_transactions.sh.template`:

```bash
#!/bin/bash
set -euo pipefail
cd "__REPO__"
exec /opt/homebrew/bin/uv run --project packages/league-automation \
  ug sleeper transactions --quiet
```

- [ ] **Step 4: Add the jobs to the manifest**

Append to `hermes/guillotine/cron.yaml`, after the last scores job:

```yaml
  # The auction: a fact that changes once a year, synced once a day so a pick Sleeper
  # corrects reaches the board without anyone remembering. 1500 is the run-audit's own
  # daily budget. Before the draft is complete the job prints nothing and stays green.
  - name: guillotine-sleeper-draft
    agent: draft-sync
    schedule: "0 6 * * *"
    script: guillotine_sleeper_draft.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 1500
  # The executed transaction log — trades, drops, claims — at the roster sync's cadence,
  # because it moves whenever a manager does. Current and previous week each run; a full
  # backfill is `ug sleeper transactions --all` by hand.
  - name: guillotine-sleeper-transactions
    agent: transactions-sync
    schedule: "every 10m"
    script: guillotine_sleeper_transactions.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 30
```

- [ ] **Step 5: Run the manifest tests**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/hermes -v`
Expected: PASS, including `test_every_script_template_is_used_by_a_job`.

- [ ] **Step 6: Document the jobs in the runbook**

In `docs/runbooks/mac-mini.md`, section 9b's table gains two rows after `guillotine-sleeper-scores-monday`:

```markdown
| `guillotine-sleeper-draft` | `0 6 * * *` | `#guillotine-ops` |
| `guillotine-sleeper-transactions` | every 10m | `#guillotine-ops` |
```

After the paragraph that ends "exactly like the projections job." add:

```markdown
`guillotine-sleeper-draft` writes `public.draft_picks` from the league's canonical draft
(`league.draft_id`, never the drafts list — the 2025 league also carries an abandoned
one-pick draft). Before the auction is complete it prints `draft: skipped, status=…` and
exits 0; afterwards it upserts the 162 picks daily whether or not they changed. It refuses,
with the last good rows untouched, an empty payload, fewer picks than teams × rounds, any
pick with no auction amount, and any roster with no team row. `guillotine-sleeper-transactions`
writes `public.transactions` and `public.transaction_moves` from Sleeper's executed log for
the current and previous week; `ug sleeper transactions --all` backfills a season and
`--week N` does one week. Only completed records are kept. A record of an unknown kind or
naming a roster with no team row is counted, skipped, and said once in the channel — never
a failed run.
```

In section 9c's first-run block, after the `ug sleeper scores` line:

```bash
uv run --project packages/league-automation ug sleeper draft
uv run --project packages/league-automation ug sleeper transactions --all
```

- [ ] **Step 7: Run the whole agent suite and lint**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres pnpm test:agents && pnpm lint:agents`
Expected: PASS, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add hermes/guillotine/cron.yaml hermes/guillotine/scripts/guillotine_sleeper_draft.sh.template hermes/guillotine/scripts/guillotine_sleeper_transactions.sh.template packages/league-automation/tests/hermes/test_cron_manifest.py docs/runbooks/mac-mini.md
git commit -m "chore(cron): sync the auction daily and the transaction log every 10 minutes"
```

---

### Task 9: Rollout — hosted migration, first syncs, verification

**Files:** none. Operator steps against the hosted project; `.env` at the repository root carries the hosted `DATABASE_URL`.

- [ ] **Step 1: Push the migration to the hosted project**

Run: `npx supabase db push`
Expected: `20260910190000_player_card.sql` applied; `npx supabase migration list` shows it on both sides.

- [ ] **Step 2: Run the draft sync once and check the rows**

Run:

```bash
uv run --project packages/league-automation ug sleeper draft
```

Expected: `draft: 162 picks`. Verify:

```bash
uv run --project packages/league-automation python - <<'EOF'
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as c, c.cursor() as cur:
    cur.execute("select count(*), sum(amount), min(amount), max(amount) from public.draft_picks")
    print("picks, spent, min, max:", cur.fetchone())
    cur.execute("select count(distinct team_id) from public.draft_picks")
    print("teams:", cur.fetchone()[0])
EOF
```

Expected: `(162, 2293, 1, 80)` and 18 teams.

- [ ] **Step 3: Backfill the transaction log and check it**

Run:

```bash
uv run --project packages/league-automation ug sleeper transactions --all
```

Expected: `transactions: N transactions, M moves, weeks 1-<current>` with N ≥ 8. Verify:

```bash
uv run --project packages/league-automation python - <<'EOF'
import os, psycopg
from dotenv import load_dotenv
load_dotenv()
with psycopg.connect(os.environ["DATABASE_URL"]) as c, c.cursor() as cur:
    cur.execute("select kind, count(*) from public.transactions group by kind order by 1")
    print(cur.fetchall())
    cur.execute("select count(*) from public.transaction_moves")
    print("moves:", cur.fetchone()[0])
EOF
```

Expected: at least `[('free_agent', 5), ('trade', 3)]` and a move count matching `adds + drops` over the completed records.

- [ ] **Step 4: Hand the cron entries to the Mac mini**

The mini's `install.sh` renders every `*.sh.template` and registers `cron.yaml` idempotently. Tell Ben to run it there (`hermes/guillotine/install.sh`) and to watch two transactions cycles in `#guillotine-ops`. Nothing to commit.

---

## Self-review

**Spec coverage.** Tables (Task 1: every column, key, policy, grant, no realtime); `SleeperLeague.draft_id`, `get_draft`, `get_draft_picks`, `get_transactions` (Task 2); `draft_picks` rules — canonical draft id, skipped until complete, the four refusals, `drafted_at` from `start_time`, `position` from the pick, upsert on `(season_id, sleeper_player_id)` (Task 4); transactions rules — complete only, `week = leg`, `occurred_at` preference, `team_ids`, `faab_moves`, `waiver_bid`, `raw`, moves per side, unknown kind and unmatched roster counted (Task 5); the two CLIs, the week rule with its clamp, `--all`, `--week`, off-season no-op, counts-only output, ops notes (Tasks 6–7); cron entries, agents, script templates, runbook (Task 8); rollout order (Task 9). The spec's "not a failed run" rule for unknown kinds and unmatched rosters is Task 5's loader plus Task 7's notes. Nothing in the Mac mini half of the spec is without a task.

**Placeholder scan.** None.

**Type consistency.** `sync_draft(client, conn, league_id, season_id, now)` is called that way in Task 4's tests and Task 6's fake; `sync_transactions(client, conn, league_id, season_id, weeks, now)` in Task 5's tests and Task 7's fake; `DraftReport(picks, status)` and `TransactionReport(transactions, moves, weeks, unknown_kinds, unmatched_rosters, malformed)` match their constructors; `teams_by_roster_id(conn, season_id)` is the module function in Tasks 3–5 and the method on `ScoreRepository` keeps its name.
