# League History Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load past-season trades into Supabase once, from the league chat archive and the contracts spreadsheet, as dated league history that the Trade Advisor and the League Concierge can reason about — reading BlueBubbles strictly read-only and never touching the current season.

**Architecture:** A one-time operator command, `ug trades backfill`, drives the Trade Registrar's own pipeline (detect, one structured-output call, deterministic resolution, validate, `TradeRepository.accept`) over two ordered passes: the chat archive first, chronologically, then the contracts spreadsheet as a terms-correcting revision. It constructs no `TradeRegistrar`, no `DeliveryService`, and no notifier, so no code path exists that could post to the chat. Season rows, historical members, and historical teams come from Sleeper's `previous_league_id` chain, verified before insertion, and those teams give resolution a historical `RosterIndex`. Rows that cannot be resolved go to a git-ignored review file that Ben shrinks with aliases and reruns.

**Tech Stack:** Python 3.12, Pydantic 2.13.5, httpx 0.28.1 with respx 0.23.1 for tests, psycopg 3.3.5, openpyxl 3.1.5, `zoneinfo` (stdlib), Supabase migrations with pgTAP, the BlueBubbles REST API on the Mac mini, Sleeper `GET /v1/league/<id>`.

**Spec:** `docs/superpowers/specs/2026-09-09-league-history-backfill-design.md`, which inherits `docs/superpowers/specs/2026-08-27-trade-registrar-agent-design.md` and `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`.

## Global Constraints

- **Read-only against BlueBubbles.** The backfill issues exactly three request shapes: `GET /api/v1/ping`, `POST /api/v1/chat/query` (a read-only listing, needed only to find the chat by display name), and `GET /api/v1/chat/{guid}/message`. It never calls `POST /api/v1/message/text`, never touches `/api/v1/webhook`, and holds no reference to `DeliveryService`. Two tests enforce this: a respx test that registers the send route and asserts `call_count == 0`, and a source test that asserts no module in `ultimate_guillotine/history/` contains the strings `DeliveryService` or `send_text`.
- **The chat is never named in the repository.** The chat GUID comes from the `private.delivery_targets` production row when one exists; otherwise from a display name the operator passes on the command line as `--chat-name`. No chat name, GUID, handle, phone number, or group name is written into any file in this repository, any test fixture, any log line, or any Discord message.
- **Never the current season.** The command refuses when `--season` equals the newest `public.seasons` row, and the archive is read only inside `season_window(year)` — `1 Aug <year> 00:00:00 America/Chicago` inclusive to `1 Mar <year+1> 00:00:00 America/Chicago` exclusive — which ends months before the next season's first alert.
- **Never in production.** Without `--dry-run` the command exits 2 when `DELIVERY_MODE` is `production`, read off settings before a database connection is opened.
- **Codes are chronological.** Every candidate in a pass is sorted by its message time ascending before the first `accept`, and the code prefix is forced to `T` regardless of `DELIVERY_MODE` — `code_prefix_for` returns `TEST` in test mode and history must not be numbered as gate traffic.
- **Dated events.** `TradeRepository.accept` takes an explicit occurrence time; `public.league_events.occurred_at` and the new `public.trade_revisions.occurred_at` carry the message's real `sent_at`, and the revise-by-context window is measured against that time, not against insertion time.
- **What is never copied:** no message body beyond the 2000-character excerpt of an accepted alert; nothing at all from a message that fails `is_trade_candidate`; no handles, phone numbers, email addresses, Messages display names, attachments, reactions, read state, or tapbacks; no chat GUID in cleartext anywhere, only `chat_guid_hash`; `sender_hash` is always null.
- **The terminal prints codes, not prose.** Per-row output is `<source> <ordinal>: <outcome>` where an unresolved row prints its review code (`ambiguous-member`, `unknown-player`, `unclear`, `invalid`) and never the model's sentence, which quotes the message. The offending token reaches the review file only.
- **The review file** is `data/private/backfill/<season>-review.tsv`. `data/private/*` is already git-ignored; no new `.gitignore` entry is needed and none is added. It is rewritten from scratch on every run so a rerun visibly shrinks it.
- **Idempotent reruns.** Each row reserves `trade:backfill:<season>:<source-guid>` in `private.agent_runs`. A prior `succeeded` or `duplicate` skips the row with no model call; anything else re-reserves with a per-attempt suffix. Season, member, and team writes are upserts.
- **`automation_worker` gains no DELETE grant.** Rollback is Ben in the Supabase dashboard.
- All commands run from the repository root with `uv run --project packages/league-automation ...`; `pnpm test:agents` and `pnpm lint:agents` are the suite commands; DB-backed tests use the shared `conn` fixture in `packages/league-automation/tests/conftest.py` (skips without `TEST_DATABASE_URL`, rolls back). Follow TDD. Keep lines at or under 100 characters.
- Commit after each task with a conventional message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## External Interfaces

**The model client is not OpenRouter here.** `ultimate_guillotine.ai.hermes.HermesStructuredClient` is being built in a parallel plan. It satisfies the same interface the existing `StructuredOutputClient` does:

```python
parse(system: str, user: str, schema: type[T], schema_name: str) -> tuple[T, AIUsage]
```

where `AIUsage` is `ultimate_guillotine.ai.openrouter.AIUsage(response_id, prompt_tokens, completion_tokens, model)`. Nothing in this plan imports `HermesStructuredClient` directly except `cli/trades.py`, and every test in this plan uses a fake with that one method. If `ultimate_guillotine.ai.hermes` does not exist yet when Task 9 runs, wire the CLI to `build_ai(deps)` (the existing OpenRouter client) and leave a one-line comment naming `HermesStructuredClient` as the intended client; do not stub the module.

**BlueBubbles read paths** (assumed shapes; Task 1 Step 6 verifies them with `curl` against the running server before the task is committed):

- `POST /api/v1/chat/query?password=<pw>` with body `{"limit": 1000, "offset": N, "with": [], "sort": "lastmessage"}` returns `{"data": [{"guid": "...", "displayName": "..."}, ...]}`. A page shorter than `limit` is the last page.
- `GET /api/v1/chat/{urlencoded guid}/message?password=<pw>&after=0&sort=ASC&limit=1000&offset=N&with=handle` returns `{"data": [<message record>, ...]}` in the same record shape `_record_to_message` already parses. A page shorter than `limit` is the last page.

**Existing repository interfaces this plan builds on (do not redefine):**

- `ultimate_guillotine.messages.bluebubbles.BlueBubblesClient(server_url, password, http)`, `.messages_after(chat_guid, after, limit)`, `._request(method, path, **kwargs)`; `InboundMessage(guid, chat_guid, sender_address, text, is_from_me, is_group, sent_at)`; `_record_to_message(record) -> InboundMessage | None`.
- `ultimate_guillotine.trades.detect.is_trade_candidate(text) -> bool`, `ALERT`.
- `ultimate_guillotine.trades.resolve.resolve_extracted(...)`, `validate(proposal)`, `Unresolved`, `RosterIndex`, `build_roster_index(client, conn, league_id, season)`.
- `ultimate_guillotine.trades.repository.TradeRepository(conn, code_prefix)`, `.accept`, `.rescind`, `.find_by_context`, `.find_by_id`, `.list_recent`, `REVISE_WINDOW_HOURS = 72`, `code_prefix_for(mode)`.
- `ultimate_guillotine.trades.fingerprint.trade_context_key(proposal)`, `message_fingerprint(text)`.
- `ultimate_guillotine.trades.extract.extract_trade(client, text, season, week_hint, member_names)`, `PROMPT_VERSION`.
- `ultimate_guillotine.data.repositories.RunRepository.reserve/.finish`, `SourceMessageRepository.upsert`, `SourceMessage`, `SeasonRepository.current/.exists`, `TargetRepository.get(mode)`, `MemberAliasRepository.all_members`, `chat_guid_hash(guid)`.
- `ultimate_guillotine.sleeper.client.SleeperClient.get_league/.get_users/.get_rosters`; `sleeper/models.py` `SleeperLeague`, `SleeperUser` (`.team_name`), `SleeperRoster`.
- `ultimate_guillotine.sleeper.players.PlayerRepository.all_active() -> list[Player]`.
- `ultimate_guillotine.cli.deps.build_deps() -> Deps(settings, conn, client, notifier)`, `build_ai(deps)`.
- `ultimate_guillotine.cli.trades.load_replay_rows(path)`, `dry_run_pipeline(...)`, `NOT_A_TRADE`, `positive_int`, `SUMMARY_FIXED`, `SUMMARY_EXTRA`.

## File Structure

```text
packages/league-automation/src/ultimate_guillotine/
  messages/bluebubbles.py        # + chat_query, messages_page (read paths only)
  sleeper/models.py              # + SleeperLeague.previous_league_id
  data/repositories.py           # + SeasonRepository.upsert, RunRepository.status_for
  trades/models.py               # + TradeProposal.source
  trades/repository.py           # accept(occurred_at, revise_within_hours); list_for_season
  trades/resolve.py              # Unresolved gains .code and .token
  trades/pipeline.py             # dry_run_pipeline, NOT_A_TRADE, summary_line (moved out of cli)
  history/__init__.py
  history/archive.py             # season_window, find_chat_guid, scan_messages
  history/chain.py               # find_season_league, ensure_season_row
  history/teams.py               # sync_historical_teams
  history/review.py              # ReviewRow, review_path, write_review
  history/candidates.py          # Candidate, ContractRow, chat/xlsx candidates, ordering
  history/runkeys.py             # BACKFILL_AGENT, backfill_key, reserve_row
  history/runner.py              # BackfillRunner: one row, one pass
  history/report.py              # spot_check_lines, dedupe_report_lines
  cli/trades.py                  # + ug trades backfill
supabase/migrations/<ts>_trade_revision_occurred_at.sql
supabase/tests/trades.sql        # + occurred_at column assertions
docs/runbooks/mac-mini.md        # + section "9. League history backfill"
packages/league-automation/tests/
  history/{__init__,test_archive,test_chain,test_teams,test_review,
           test_candidates,test_runkeys,test_runner,test_report,test_read_only}.py
  messages/test_bluebubbles.py   # + chat_query, messages_page
  trades/{test_repository,test_resolve,test_registrar}.py
  cli/test_trades_backfill.py
```

---

### Task 1: Read-only archive reader

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/messages/bluebubbles.py`
- Create: `packages/league-automation/src/ultimate_guillotine/history/__init__.py` (empty)
- Create: `packages/league-automation/src/ultimate_guillotine/history/archive.py`
- Create: `packages/league-automation/tests/history/__init__.py` (empty)
- Create: `packages/league-automation/tests/history/test_archive.py`
- Modify: `packages/league-automation/tests/messages/test_bluebubbles.py`

**Interfaces:**
- Consumes: `BlueBubblesClient._request`, `_record_to_message`, `InboundMessage`.
- Produces:
  - `BlueBubblesClient.chat_query(limit: int = 1000, offset: int = 0) -> list[dict]`
  - `BlueBubblesClient.messages_page(chat_guid: str, offset: int, limit: int = 1000) -> list[InboundMessage]`
  - `history/archive.py`: `SEASON_TZ = ZoneInfo("America/Chicago")`, `PAGE_SIZE = 1000`,
    `season_window(year: int) -> tuple[datetime, datetime]`,
    `find_chat_guid(client, display_name: str) -> str | None`,
    `scan_messages(client, chat_guid: str, window: tuple[datetime, datetime], page_size: int = PAGE_SIZE) -> Iterator[InboundMessage]`

- [ ] **Step 1: Write the failing client tests**

```python
# append to packages/league-automation/tests/messages/test_bluebubbles.py
@respx.mock
def test_chat_query_posts_paging_body_and_returns_raw_chats() -> None:
    route = respx.post("http://bb.local/api/v1/chat/query").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": [{"guid": "g", "displayName": "d"}]})
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    assert client.chat_query(limit=1000, offset=2000) == [{"guid": "g", "displayName": "d"}]
    body = json.loads(route.calls.last.request.content)
    assert body == {"limit": 1000, "offset": 2000, "with": [], "sort": "lastmessage"}
    assert route.calls.last.request.url.params["password"] == "pw"


@respx.mock
def test_messages_page_asks_for_the_whole_archive_from_the_start() -> None:
    route = respx.get("http://bb.local/api/v1/chat/iMessage%3B%2B%3Bchat-test/message").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": [json.loads(FIXTURE.read_text())["data"]]})
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    out = client.messages_page("iMessage;+;chat-test", offset=3000, limit=1000)
    params = route.calls.last.request.url.params
    assert params["after"] == "0" and params["sort"] == "ASC"
    assert params["limit"] == "1000" and params["offset"] == "3000"
    assert len(out) == 1 and out[0].guid
```

- [ ] **Step 2: Write the failing archive tests**

```python
# packages/league-automation/tests/history/test_archive.py
from datetime import UTC, datetime

import pytest

from ultimate_guillotine.history.archive import (
    SEASON_TZ,
    find_chat_guid,
    scan_messages,
    season_window,
)
from ultimate_guillotine.messages.bluebubbles import InboundMessage


def msg(guid: str, when: datetime) -> InboundMessage:
    return InboundMessage(guid=guid, chat_guid="c", sender_address=None, text="t",
                          is_from_me=False, is_group=True, sent_at=when)


class FakeClient:
    """Pages of chats and messages, plus a record of every call made."""

    def __init__(self, chats: list[list[dict]], pages: list[list[InboundMessage]]) -> None:
        self.chats, self.pages = chats, pages
        self.offsets: list[int] = []

    def chat_query(self, limit: int = 1000, offset: int = 0) -> list[dict]:
        index = offset // limit
        return self.chats[index] if index < len(self.chats) else []

    def messages_page(self, chat_guid: str, offset: int, limit: int = 1000) -> list[InboundMessage]:
        self.offsets.append(offset)
        index = offset // limit
        return self.pages[index] if index < len(self.pages) else []


def test_season_window_runs_from_august_to_the_following_march() -> None:
    start, end = season_window(2025)
    assert start == datetime(2025, 8, 1, tzinfo=SEASON_TZ)
    assert end == datetime(2026, 3, 1, tzinfo=SEASON_TZ)
    # The next season's first alert can never fall inside the previous window.
    assert season_window(2026)[0] > end


def test_find_chat_guid_matches_the_display_name_exactly_across_pages() -> None:
    client = FakeClient([[{"guid": "a", "displayName": "Other"}] * 1,
                         [{"guid": "b", "displayName": "Wanted"}]], [])
    assert find_chat_guid(client, "Wanted", page_size=1) == "b"
    assert find_chat_guid(client, "wanted", page_size=1) is None
    assert find_chat_guid(client, "Missing", page_size=1) is None


def test_scan_messages_pages_forward_until_a_short_page() -> None:
    inside = datetime(2025, 10, 1, tzinfo=UTC)
    client = FakeClient([], [[msg("g1", inside), msg("g2", inside)], [msg("g3", inside)]])
    out = list(scan_messages(client, "c", season_window(2025), page_size=2))
    assert [m.guid for m in out] == ["g1", "g2", "g3"]
    assert client.offsets == [0, 2]


def test_scan_messages_drops_messages_outside_the_season_window_and_stops_after_it() -> None:
    before = datetime(2025, 3, 1, tzinfo=UTC)
    inside = datetime(2025, 10, 1, tzinfo=UTC)
    after = datetime(2026, 9, 8, tzinfo=UTC)
    client = FakeClient([], [[msg("old", before), msg("keep", inside)], [msg("live", after)],
                             [msg("never", inside)]])
    out = list(scan_messages(client, "c", season_window(2025), page_size=2))
    assert [m.guid for m in out] == ["keep"]
    # The scan is sorted ascending, so the first message past the window ends it.
    assert client.offsets == [0, 2]
```

- [ ] **Step 3: Run the tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_archive.py packages/league-automation/tests/messages/test_bluebubbles.py -v`

Expected: FAIL — `ultimate_guillotine.history` does not exist and `chat_query` is not defined.

- [ ] **Step 4: Implement the two client read paths**

```python
# packages/league-automation/src/ultimate_guillotine/messages/bluebubbles.py, after messages_after
    def chat_query(self, limit: int = 1000, offset: int = 0) -> list[dict]:
        """One page of the server's chat list, newest conversation first.

        A POST, but a read: BlueBubbles has no GET that lists chats, and the
        backfill needs the list only to turn a display name into a GUID. It is
        the single non-GET call the history backfill is allowed to make.
        """
        body = {"limit": limit, "offset": offset, "with": [], "sort": "lastmessage"}
        return self._request("POST", "/api/v1/chat/query", json=body).get("data") or []

    def messages_page(
        self, chat_guid: str, offset: int, limit: int = 1000
    ) -> list["InboundMessage"]:
        """One page of a chat's whole archive, oldest first.

        ``after=0`` means "from the beginning of time": the backfill walks
        forward from the start of the archive and stops itself once the
        messages pass the season it is loading.
        """
        params = {"after": "0", "sort": "ASC", "limit": str(limit),
                  "offset": str(offset), "with": "handle"}
        data = self._request(
            "GET", f"/api/v1/chat/{quote(chat_guid, safe='')}/message", params=params
        ).get("data") or []
        return [m for m in (_record_to_message(r) for r in data) if m]
```

- [ ] **Step 5: Implement the archive module**

```python
# packages/league-automation/src/ultimate_guillotine/history/archive.py
"""Read-only walks over the league chat archive.

Nothing here can write: the only client methods it calls are ``chat_query``
and ``messages_page``, both reads. The window is what keeps a backfill off the
live season -- the scan stops at the first message past the season's end rather
than reading the archive to its end and filtering afterwards.
"""

from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

SEASON_TZ = ZoneInfo("America/Chicago")
PAGE_SIZE = 1000


def season_window(year: int) -> tuple[datetime, datetime]:
    """The half-open span a season's messages live in, in league time.

    August 1 of the season year up to (not including) March 1 of the next: wide
    enough for a preseason trade and for a February dynasty deal, and closed
    months before the following season's first alert, so a 2025 backfill can
    never swallow a 2026 announcement.
    """
    return (
        datetime(year, 8, 1, tzinfo=SEASON_TZ),
        datetime(year + 1, 3, 1, tzinfo=SEASON_TZ),
    )


def find_chat_guid(client, display_name: str, page_size: int = PAGE_SIZE) -> str | None:
    """The GUID of the chat whose display name is exactly ``display_name``.

    Exact, case-sensitive, and never fuzzy: reading the wrong conversation is
    the one mistake this command cannot take back. Returns ``None`` when no
    chat matches, which the caller turns into a refusal rather than a guess.
    The name is never logged, and neither is the GUID.
    """
    offset = 0
    while True:
        page = client.chat_query(limit=page_size, offset=offset)
        for chat in page:
            if chat.get("displayName") == display_name:
                return chat.get("guid")
        if len(page) < page_size:
            return None
        offset += page_size


def scan_messages(
    client, chat_guid: str, window: tuple[datetime, datetime], page_size: int = PAGE_SIZE
) -> Iterator[datetime]:
    """Yield every message inside ``window``, oldest first.

    The archive is read ascending from its start, so the first message at or
    past the window's end means every later message is too and the walk ends
    there. Messages before the window are skipped, not stopped on -- the
    archive reaches back to 2020 and the window may start years in.
    """
    start, end = window
    offset = 0
    while True:
        page = client.messages_page(chat_guid, offset=offset, limit=page_size)
        for message in page:
            if message.sent_at >= end:
                return
            if message.sent_at >= start:
                yield message
        if len(page) < page_size:
            return
        offset += page_size
```

Fix the annotation while implementing: `scan_messages` returns `Iterator[InboundMessage]`; import `InboundMessage` from `ultimate_guillotine.messages.bluebubbles` for the annotation only.

- [ ] **Step 6: Verify the two endpoint shapes against the running server (Mac mini)**

Run, on the Mac mini, with the password from the environment and the production chat GUID never echoed:

```bash
curl -s -X POST "$BLUEBUBBLES_SERVER_URL/api/v1/chat/query?password=$BLUEBUBBLES_PASSWORD" \
  -H 'Content-Type: application/json' \
  -d '{"limit":1,"offset":0,"with":[],"sort":"lastmessage"}' | python3 -c \
  'import json,sys; d=json.load(sys.stdin)["data"][0]; print(sorted(k for k in d if k in ("guid","displayName")))'
```

Expected: `['displayName', 'guid']`. If either key is missing or the route 404s, stop and report the real shape before changing the code — the plan's assumption is wrong, not the server.

- [ ] **Step 7: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation
git commit -m "feat: add read-only BlueBubbles archive paging for history"
```

---

### Task 2: Verified `previous_league_id` chain and the season row

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/models.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/data/repositories.py` (`SeasonRepository.upsert`)
- Create: `packages/league-automation/src/ultimate_guillotine/history/chain.py`
- Create: `packages/league-automation/tests/history/test_chain.py`
- Modify: `packages/league-automation/tests/sleeper/test_client.py`
- Modify: `packages/league-automation/tests/data/test_repositories.py`

**Interfaces:**
- Consumes: `SleeperClient.get_league`, `SleeperLeague`, `psycopg.Connection`.
- Produces:
  - `SleeperLeague.previous_league_id: str | None = None`
  - `SeasonRepository.upsert(year: int, sleeper_league_id: str, rules_version: str, expected_rosters: int) -> int` (returns the season id; idempotent)
  - `history/chain.py`: `class LeagueChainError(Exception)`,
    `find_season_league(client, start_league_id: str, year: int, expected_rosters: int) -> str`,
    `rules_version_for(year: int) -> str` returning `f"historical-{year}"`

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/history/test_chain.py
import pytest

from ultimate_guillotine.history.chain import LeagueChainError, find_season_league, rules_version_for
from ultimate_guillotine.sleeper.models import SleeperLeague


def league(league_id: str, season: str, previous: str | None, rosters: int = 18) -> SleeperLeague:
    return SleeperLeague(league_id=league_id, name="L", season=season,
                         total_rosters=rosters, previous_league_id=previous)


class FakeClient:
    def __init__(self, leagues: dict[str, SleeperLeague]) -> None:
        self.leagues, self.asked = leagues, []

    def get_league(self, league_id: str) -> SleeperLeague:
        self.asked.append(league_id)
        if league_id not in self.leagues:
            raise KeyError(league_id)
        return self.leagues[league_id]


def chain() -> FakeClient:
    return FakeClient({
        "L2026": league("L2026", "2026", "L2025"),
        "L2025": league("L2025", "2025", "L2024"),
        "L2024": league("L2024", "2024", None),
    })


def test_walks_back_to_the_requested_season() -> None:
    client = chain()
    assert find_season_league(client, "L2026", 2024, 18) == "L2024"
    assert client.asked == ["L2026", "L2025", "L2024"]


def test_rules_version_is_the_historical_placeholder() -> None:
    assert rules_version_for(2024) == "historical-2024"


def test_refuses_a_league_whose_roster_count_disagrees() -> None:
    client = FakeClient({"L2026": league("L2026", "2026", "L2025"),
                         "L2025": league("L2025", "2025", None, rosters=12)})
    with pytest.raises(LeagueChainError, match="expected 18 rosters"):
        find_season_league(client, "L2026", 2025, 18)


def test_refuses_when_the_chain_ends_before_the_season() -> None:
    with pytest.raises(LeagueChainError, match="chain ends"):
        find_season_league(chain(), "L2026", 2022, 18)


def test_refuses_a_season_newer_than_the_starting_league() -> None:
    with pytest.raises(LeagueChainError, match="never walks forward"):
        find_season_league(chain(), "L2025", 2026, 18)
```

```python
# add to packages/league-automation/tests/data/test_repositories.py
def test_season_upsert_is_idempotent(conn) -> None:
    repo = SeasonRepository(conn)
    first = repo.upsert(2024, "L2024", "historical-2024", 18)
    second = repo.upsert(2024, "L2024", "historical-2024", 18)
    assert first == second
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.seasons where year = 2024")
        assert cur.fetchone()[0] == 1
```

```python
# add to packages/league-automation/tests/sleeper/test_client.py
def test_league_keeps_previous_league_id_and_defaults_to_none() -> None:
    from ultimate_guillotine.sleeper.models import SleeperLeague
    with_previous = SleeperLeague.model_validate(
        {"league_id": "a", "name": "L", "season": "2025", "total_rosters": 18,
         "previous_league_id": "b"}
    )
    assert with_previous.previous_league_id == "b"
    without = SleeperLeague.model_validate(
        {"league_id": "a", "name": "L", "season": "2025", "total_rosters": 18}
    )
    assert without.previous_league_id is None
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_chain.py packages/league-automation/tests/sleeper/test_client.py -v`

Expected: FAIL — `previous_league_id` is not a field and `ultimate_guillotine.history.chain` does not exist.

- [ ] **Step 3: Add the field and the season upsert**

```python
# packages/league-automation/src/ultimate_guillotine/sleeper/models.py, inside SleeperLeague
    previous_league_id: str | None = None
```

```python
# packages/league-automation/src/ultimate_guillotine/data/repositories.py, in SeasonRepository
    def upsert(
        self, year: int, sleeper_league_id: str, rules_version: str, expected_rosters: int
    ) -> int:
        """Create or refresh a season row, returning its id.

        Backfilling a past season has to be rerunnable, and every trade hangs
        off this row, so the year's unique constraint carries the idempotency
        rather than a prior existence check.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.seasons
                    (year, sleeper_league_id, rules_version, expected_rosters)
                values (%s, %s, %s, %s)
                on conflict (year) do update
                    set sleeper_league_id = excluded.sleeper_league_id,
                        rules_version = excluded.rules_version,
                        expected_rosters = excluded.expected_rosters
                returning id
                """,
                (year, sleeper_league_id, rules_version, expected_rosters),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("insert returned no id")
            return row[0]
```

- [ ] **Step 4: Implement the chain walk**

```python
# packages/league-automation/src/ultimate_guillotine/history/chain.py
"""Find a past season's Sleeper league by walking ``previous_league_id`` back.

The walk is verified, never trusted. A league id is only accepted when the
league it names reports the year being loaded and the roster count that season
is expected to have had; anything else raises rather than guessing, because a
wrong league id would attach another league's rosters to this league's history.
"""


class LeagueChainError(Exception):
    """The walk could not reach a verified league for the requested season."""


def rules_version_for(year: int) -> str:
    """The rules document a past season is recorded under.

    A placeholder: the current rules document does not describe how the league
    played in 2023, and inventing a version would be worse than admitting that.
    """
    return f"historical-{year}"


def find_season_league(client, start_league_id: str, year: int, expected_rosters: int) -> str:
    """The Sleeper league id for ``year``, verified, walking back from ``start_league_id``."""
    league_id: str | None = start_league_id
    seen: set[str] = set()
    while league_id is not None and league_id not in seen:
        seen.add(league_id)
        league = client.get_league(league_id)
        found = int(league.season)
        if found == year:
            if league.total_rosters != expected_rosters:
                raise LeagueChainError(
                    f"league for {year} expected {expected_rosters} rosters, "
                    f"got {league.total_rosters}"
                )
            return league.league_id
        if found < year:
            # The walk only goes backwards; a league older than the season asked
            # for means the season never existed on this chain.
            raise LeagueChainError(f"the chain never walks forward to {year}")
        league_id = league.previous_league_id
    raise LeagueChainError(f"the chain ends before {year}")
```

- [ ] **Step 5: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

Expected: PASS. The DB test skips unless `TEST_DATABASE_URL` is set; set it and rerun once to see it pass for real.

```bash
git add packages/league-automation
git commit -m "feat: resolve past-season Sleeper leagues from the previous_league_id chain"
```

---

### Task 3: Historical members, teams, and the historical roster index

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/history/teams.py`
- Create: `packages/league-automation/tests/history/test_teams.py`

**Interfaces:**
- Consumes: `SleeperClient.get_users/.get_rosters`, `SeasonRepository.upsert` (Task 2), `build_roster_index`.
- Produces:
  - `@dataclass(frozen=True) class TeamSyncReport: members_matched: int; members_created: int; teams: int; skipped_rosters: int`
  - `sync_historical_teams(client, conn, year: int, league_id: str) -> TeamSyncReport`

**Why not `sleeper.sync.sync_season`:** it matches members by display name only, requires every roster to have a user, and fails the whole season when the team count differs from `expected_rosters`. History needs the opposite of all three: match by `sleeper_user_id` first (a member who renamed themselves still has the same Sleeper id), create a member for someone who has since left, and survive a roster whose owner Sleeper no longer returns.

- [ ] **Step 1: Write the failing test**

```python
# packages/league-automation/tests/history/test_teams.py
import pytest

from ultimate_guillotine.data.repositories import SeasonRepository
from ultimate_guillotine.history.teams import sync_historical_teams
from ultimate_guillotine.sleeper.models import SleeperRoster, SleeperUser
from ultimate_guillotine.trades.resolve import build_roster_index


class FakeSleeper:
    def __init__(self, users, rosters) -> None:
        self._users, self._rosters = users, rosters

    def get_users(self, league_id: str):
        return self._users

    def get_rosters(self, league_id: str):
        return self._rosters


def users() -> list[SleeperUser]:
    return [
        SleeperUser(user_id="u1", display_name="Member01", metadata={"team_name": "Old Team"}),
        SleeperUser(user_id="u2", display_name="DepartedMember", metadata={}),
    ]


def rosters() -> list[SleeperRoster]:
    return [
        SleeperRoster(roster_id=1, owner_id="u1", players=["p1", "p2"]),
        SleeperRoster(roster_id=2, owner_id="u2", players=["p3"]),
        SleeperRoster(roster_id=3, owner_id="ghost", players=["p4"]),
    ]


def test_matches_existing_members_creates_departed_ones_and_skips_orphan_rosters(conn) -> None:
    SeasonRepository(conn).upsert(2024, "L2024", "historical-2024", 18)
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Member01') "
            "on conflict (display_name) do update set display_name = excluded.display_name"
        )

    report = sync_historical_teams(FakeSleeper(users(), rosters()), conn, 2024, "L2024")

    assert report.members_matched == 1
    assert report.members_created == 1
    assert report.teams == 2
    assert report.skipped_rosters == 1


def test_is_rerunnable_and_feeds_a_historical_roster_index(conn) -> None:
    SeasonRepository(conn).upsert(2024, "L2024", "historical-2024", 18)
    client = FakeSleeper(users(), rosters())
    sync_historical_teams(client, conn, 2024, "L2024")
    second = sync_historical_teams(client, conn, 2024, "L2024")
    assert second.members_created == 0 and second.teams == 2

    index = build_roster_index(client, conn, "L2024", 2024)
    holdings = sorted(sorted(ids) for ids in index.holdings.values())
    assert holdings == [["p1", "p2"], ["p3"]]


def test_matches_a_renamed_member_by_their_sleeper_user_id(conn) -> None:
    """A member who changed their Sleeper username between seasons is the same
    person: the team row from another season carries the id that proves it."""
    SeasonRepository(conn).upsert(2024, "L2024", "historical-2024", 18)
    SeasonRepository(conn).upsert(2025, "L2025", "historical-2025", 18)
    with conn.cursor() as cur:
        cur.execute("insert into public.members (display_name) values ('NewName') returning id")
        member_id = cur.fetchone()[0]
        cur.execute("select id from public.seasons where year = 2025")
        cur.execute(
            """
            insert into public.teams
                (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
            values ((select id from public.seasons where year = 2025), %s, 'u1', 9, 'T')
            """,
            (member_id,),
        )

    report = sync_historical_teams(FakeSleeper(users(), rosters()), conn, 2024, "L2024")

    assert report.members_matched == 1 and report.members_created == 1
    with conn.cursor() as cur:
        cur.execute(
            """
            select count(*) from public.teams t join public.seasons s on s.id = t.season_id
            where s.year = 2024 and t.member_id = %s
            """,
            (member_id,),
        )
        assert cur.fetchone()[0] == 1
```

- [ ] **Step 2: Run red**

Run: `TEST_DATABASE_URL=... uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_teams.py -v`

Expected: FAIL — `ultimate_guillotine.history.teams` does not exist. Without `TEST_DATABASE_URL` the tests skip; set it before claiming this task done.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/history/teams.py
"""Members and teams for a past season, from that season's Sleeper league.

Resolution needs somebody to attribute a 2023 trade to, and a trade whose party
cannot be resolved is worth less than a member row nobody plays against any
more -- so a member who has since left the league is created rather than
dropped. Nothing here writes elimination state, scores, or events.
"""

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class TeamSyncReport:
    members_matched: int
    members_created: int
    teams: int
    skipped_rosters: int


def sync_historical_teams(client, conn: psycopg.Connection, year: int, league_id: str):
    """Reconcile ``public.members`` and ``public.teams`` for a past season.

    Runs in one transaction; the caller commits. Every write is an upsert
    against an existing unique constraint, so rerunning is a no-op.
    """
    users = client.get_users(league_id)
    rosters = client.get_rosters(league_id)
    users_by_id = {user.user_id: user for user in users}
    matched = created = teams = skipped = 0

    with conn.transaction(), conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = %s", (year,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"no season row for year {year}")
        season_id = row[0]

        member_ids: dict[str, int] = {}
        for user in users:
            # A team row from any season proves which member a Sleeper id is,
            # even when that member has renamed themselves since.
            cur.execute(
                "select member_id from public.teams where sleeper_user_id = %s limit 1",
                (user.user_id,),
            )
            found = cur.fetchone()
            if found is None:
                cur.execute(
                    "select id from public.members where display_name = %s",
                    (user.display_name,),
                )
                found = cur.fetchone()
            if found is not None:
                member_ids[user.user_id] = found[0]
                matched += 1
                continue
            cur.execute(
                "insert into public.members (display_name) values (%s) returning id",
                (user.display_name,),
            )
            member_ids[user.user_id] = cur.fetchone()[0]
            created += 1

        for roster in rosters:
            user = users_by_id.get(roster.owner_id)
            if user is None:
                # Sleeper keeps rosters whose owner it no longer returns. A
                # season is not worth failing over one of them.
                skipped += 1
                continue
            with conn.transaction():
                cur.execute(
                    """
                    insert into public.teams
                        (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
                    values (%s, %s, %s, %s, %s)
                    on conflict (season_id, sleeper_roster_id) do update
                        set member_id = excluded.member_id,
                            sleeper_user_id = excluded.sleeper_user_id,
                            team_name = excluded.team_name
                    """,
                    (season_id, member_ids[user.user_id], user.user_id,
                     roster.roster_id, user.team_name),
                )
            teams += 1

    return TeamSyncReport(matched, created, teams, skipped)
```

The inner `conn.transaction()` is a savepoint: a second roster owned by the same member in one season violates `unique (season_id, member_id)`, and that must cost one roster, not the whole load. Wrap the insert in `try/except psycopg.errors.UniqueViolation` inside that savepoint, counting the violation as `skipped` and continuing.

- [ ] **Step 4: Run green, lint, commit**

Run: `TEST_DATABASE_URL=... pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation
git commit -m "feat: sync past-season members and teams from Sleeper"
```

---

### Task 4: Dated acceptance — `occurred_at` and the revise window

**Files:**
- Create: `supabase/migrations/<timestamp>_trade_revision_occurred_at.sql`
- Modify: `supabase/tests/trades.sql`
- Modify: `packages/league-automation/src/ultimate_guillotine/trades/models.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/trades/repository.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/trades/registrar.py`
- Modify: `packages/league-automation/tests/trades/test_repository.py`
- Modify: `packages/league-automation/tests/trades/test_registrar.py`

**Interfaces:**
- Consumes: `TradeProposal`, `trade_fingerprint`, `trade_context_key`.
- Produces:
  - `TradeProposal.source: str | None = None` (not part of `trade_fingerprint`, which names its fields explicitly)
  - `TradeRepository.accept(proposal, occurred_at: datetime | None = None, revise_within_hours: int = REVISE_WINDOW_HOURS) -> TradeAcceptance`
  - `TradeRepository.list_for_season(year: int) -> list[dict]` in `find_by_code` shape plus `occurred_at`, ordered by `trade_code`
  - `public.trade_revisions.occurred_at timestamptz`

- [ ] **Step 1: Write the failing tests**

```python
# add to packages/league-automation/tests/trades/test_repository.py
from datetime import UTC, datetime

WEEK3 = datetime(2025, 9, 25, 18, 0, tzinfo=UTC)
WEEK12 = datetime(2025, 11, 27, 18, 0, tzinfo=UTC)


def test_accept_dates_the_event_and_the_revision_from_the_message(conn, season_2025) -> None:
    repo = TradeRepository(conn)
    acceptance = repo.accept(proposal(), occurred_at=WEEK3)
    with conn.cursor() as cur:
        cur.execute(
            "select occurred_at from public.trade_revisions where trade_id = %s",
            (acceptance.trade_id,),
        )
        assert cur.fetchone()[0] == WEEK3
        cur.execute(
            "select occurred_at from public.league_events where idempotency_key like %s",
            (f"trade:{acceptance.trade_code}:%",),
        )
        assert cur.fetchone()[0] == WEEK3


def test_a_later_deal_with_the_same_context_is_a_new_trade_not_a_revision(conn, season_2025) -> None:
    """Two months apart is two deals. The window is measured from the message
    time, so writing both rows seconds apart in one backfill changes nothing."""
    repo = TradeRepository(conn)
    first = repo.accept(proposal(faab=100), occurred_at=WEEK3)
    second = repo.accept(proposal(faab=200), occurred_at=WEEK12)
    assert second.status == "created"
    assert second.trade_code != first.trade_code


def test_a_wide_window_lets_a_spreadsheet_row_revise_the_chat_trade(conn, season_2025) -> None:
    repo = TradeRepository(conn)
    first = repo.accept(proposal(faab=100), occurred_at=WEEK3)
    second = repo.accept(proposal(faab=200), occurred_at=WEEK12, revise_within_hours=24 * 400)
    assert second.status == "revised"
    assert second.trade_code == first.trade_code


def test_source_marks_a_spreadsheet_revision_without_changing_the_fingerprint() -> None:
    from ultimate_guillotine.trades.fingerprint import trade_fingerprint
    plain = proposal()
    marked = plain.model_copy(update={"source": "contracts-xlsx"})
    assert marked.source == "contracts-xlsx"
    assert trade_fingerprint(marked) == trade_fingerprint(plain)


def test_list_for_season_returns_accepted_trades_in_code_order(conn, season_2025) -> None:
    repo = TradeRepository(conn)
    repo.accept(proposal(faab=100), occurred_at=WEEK3)
    repo.accept(proposal(faab=200), occurred_at=WEEK12)
    codes = [row["trade_code"] for row in repo.list_for_season(2025)]
    assert codes == sorted(codes) and len(codes) == 2
```

`proposal(faab=...)` and the `season_2025` fixture: reuse the helpers already in `tests/trades/test_repository.py`; if the existing helper takes no arguments, give it a keyword-only `faab: int = 450` that varies the FAAB asset's `amount`, and add a `season_2025` fixture that calls `SeasonRepository(conn).upsert(2025, "L2025", "historical-2025", 18)`.

```python
# add to packages/league-automation/tests/trades/test_registrar.py
def test_accept_is_dated_from_the_announcement() -> None:
    class DatingTrades(FakeTrades):
        def __init__(self):
            super().__init__()
            self.occurred_at = None

        def accept(self, proposal, occurred_at=None, revise_within_hours=72):
            self.occurred_at = occurred_at
            return super().accept(proposal)

    trades = DatingTrades()
    reg, _, _ = build(FakeAI(good_extraction()), trades=trades)
    message = msg("🚨 Member01 sends Player Alpha to Member02 for 450 FAAB")
    assert reg.handle(message) == "created"
    assert trades.occurred_at == message.sent_at
```

- [ ] **Step 2: Run red**

Run: `TEST_DATABASE_URL=... uv run --project packages/league-automation pytest packages/league-automation/tests/trades -v`

Expected: FAIL — `accept()` takes no `occurred_at`, and `public.trade_revisions.occurred_at` does not exist.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/<timestamp>_trade_revision_occurred_at.sql
-- When a trade was announced, as opposed to when this row was written. The
-- backfill writes years-old trades in one sitting, so insertion order says
-- nothing about league history; every question the Advisor asks of history
-- ("who traded with whom, and when") is asked of this column.
alter table public.trade_revisions add column occurred_at timestamptz;

create index trade_revisions_occurred_at_idx
  on public.trade_revisions (occurred_at desc nulls last);
```

Generate the filename with `date -u +%Y%m%d%H%M%S` so it sorts after `20260909032752_players_and_trade_fingerprints.sql`. No new policy or grant is needed: `public.trade_revisions` already carries its RLS policies and the worker already holds `insert, update` on it.

Add to `supabase/tests/trades.sql`:

```sql
select has_column('public', 'trade_revisions', 'occurred_at', 'revisions are dated');
select col_type_is('public', 'trade_revisions', 'occurred_at', 'timestamp with time zone',
  'revision dates are timestamptz');
```

Adjust that file's `plan(N)` count by two.

- [ ] **Step 4: Implement the repository changes**

In `trades/models.py`, add to `TradeProposal`:

```python
    #: Where these terms came from when it was not the chat: ``contracts-xlsx``
    #: for a hand-transcribed ledger row. ``None`` for a real announcement.
    #: Deliberately outside ``trade_fingerprint``, which names its fields one by
    #: one: the same terms read from two sources are the same terms.
    source: str | None = None
```

In `trades/repository.py`:

```python
    def accept(
        self,
        proposal: TradeProposal,
        occurred_at: datetime | None = None,
        revise_within_hours: int = REVISE_WINDOW_HOURS,
    ) -> TradeAcceptance:
        """Record ``proposal`` as of ``occurred_at`` (default now).

        ``revise_within_hours`` is how far back a trade with the same context
        key is still open to amendment, measured from ``occurred_at`` rather
        than from insertion time. The default is the live window; a history
        backfill matching a ledger row to the alert it corrects passes the
        season's span, and gets the same answer whether the two rows were
        written in one sitting or a week apart.

        Raises ``LookupError`` when the proposal's season has no row.
        """
        at = occurred_at or datetime.now(UTC)
        fingerprint = trade_fingerprint(proposal)
        context = trade_context_key(proposal)
        terms = proposal.model_dump(mode="json")
        try:
            with self._conn.transaction():
                return self._accept(proposal, fingerprint, context, terms, at,
                                    revise_within_hours)
        except psycopg.errors.UniqueViolation:
            with self._conn.transaction():
                duplicate = self._duplicate(fingerprint)
            if duplicate is None:
                raise
            return duplicate
```

`_accept` takes `at: datetime` and `revise_within_hours: int` and changes three statements:

```python
            # The open-trade lookup, anchored on when the trades were announced.
            cur.execute(
                """
                select t.id, t.trade_code, t.current_revision_id from public.trades t
                join public.trade_revisions r on r.id = t.current_revision_id
                where t.context_key = %s and t.status = 'accepted' and t.season_id = %s
                  and coalesce(r.occurred_at, r.created_at) > %s - make_interval(hours => %s)
                order by t.id desc
                limit 1
                """,
                (context, season_id, at, revise_within_hours),
            )
```

```python
            # ... and the event, which carries the announcement's own time.
            cur.execute(
                """
                insert into public.league_events
                    (season_id, week, event_type, occurred_at, payload, idempotency_key)
                values (%s, %s, 'trade', %s, %s, %s)
                on conflict (idempotency_key) do nothing
                """,
                (season_id, proposal.effective_week, at,
                 Jsonb({"trade_code": trade_code, "revision": revision}),
                 f"trade:{trade_code}:{fingerprint}"),
            )
```

`_insert_revision` gains an `occurred_at: datetime` parameter and writes it into the new column (add `occurred_at` to the insert's column list and `%s` list). Both call sites in `_accept` pass `at`. Import `UTC` alongside `datetime`.

Add the season listing:

```python
    def list_for_season(self, year: int) -> list[dict]:
        """Every accepted trade of one season, in trade-code order.

        Code order is chronological order for a backfilled season, which is what
        a spot check wants to walk evenly.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                {_TRADE_SELECT}
                join public.seasons s on s.id = t.season_id
                where s.year = %s and t.status = 'accepted'
                order by t.trade_code
                """,
                (year,),
            )
            return [_trade_row(row) for row in cur.fetchall()]
```

In `trades/registrar.py`, the one accept call becomes `self._trades.accept(proposal, occurred_at=msg.sent_at)`: an announcement's event belongs at the announcement's time, live traffic included, where `sent_at` is within seconds of `now()` anyway. Update `FakeTrades.accept` in `tests/trades/test_registrar.py` to accept the two new keyword arguments.

- [ ] **Step 5: Run green, push the migration, lint, commit**

Run: `TEST_DATABASE_URL=... pnpm test:agents && pnpm lint:agents && npx supabase db push && npx supabase test db`

Expected: tests PASS; the migration applies; pgTAP reports the two new assertions.

```bash
git add packages/league-automation supabase
git commit -m "feat: date trade revisions and events from the announcement"
```

---

### Task 5: Review codes and the review file

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/trades/resolve.py`
- Create: `packages/league-automation/src/ultimate_guillotine/history/review.py`
- Create: `packages/league-automation/tests/history/test_review.py`
- Modify: `packages/league-automation/tests/trades/test_resolve.py`

**Interfaces:**
- Consumes: `Unresolved`.
- Produces:
  - `Unresolved(reason: str, code: str = "unclear", token: str | None = None)` with `.reason`, `.code`, `.token`
  - `REVIEW_CODES = ("ambiguous-member", "unknown-player", "unclear", "invalid")`
  - `history/review.py`: `@dataclass(frozen=True) class ReviewRow: pass_number: int; source: str; ordinal: int; code: str; token: str`,
    `review_path(season: int, root: Path = Path("data/private/backfill")) -> Path`,
    `write_review(path: Path, rows: list[ReviewRow]) -> int`,
    `review_row(pass_number: int, source: str, ordinal: int, exc: Unresolved) -> ReviewRow`

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/history/test_review.py
from pathlib import Path

from ultimate_guillotine.history.review import ReviewRow, review_path, review_row, write_review
from ultimate_guillotine.trades.resolve import Unresolved


def test_review_path_is_under_the_gitignored_private_tree(tmp_path: Path) -> None:
    assert review_path(2025).parts[-3:] == ("private", "backfill", "2025-review.tsv")
    assert review_path(2025, root=tmp_path).parent == tmp_path


def test_review_row_carries_the_code_and_the_offending_token() -> None:
    row = review_row(1, "chat", 132, Unresolved("x", code="ambiguous-member", token="Big Ben"))
    assert row == ReviewRow(1, "chat", 132, "ambiguous-member", "Big Ben")


def test_an_unclear_row_writes_no_token_because_the_reason_quotes_the_message() -> None:
    row = review_row(1, "chat", 7, Unresolved("who sent what to whom?", code="unclear"))
    assert row.code == "unclear" and row.token == ""


def test_write_review_writes_a_header_and_one_line_per_row(tmp_path: Path) -> None:
    path = tmp_path / "2025-review.tsv"
    written = write_review(path, [ReviewRow(1, "chat", 132, "ambiguous-member", "Big Ben"),
                                  ReviewRow(2, "xlsx", 14, "unknown-player", "Old Player")])
    assert written == 2
    assert path.read_text(encoding="utf-8").splitlines() == [
        "pass\tsource\tordinal\tcode\ttoken",
        "1\tchat\t132\tambiguous-member\tBig Ben",
        "2\txlsx\t14\tunknown-player\tOld Player",
    ]


def test_write_review_replaces_the_previous_run_and_flattens_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "2025-review.tsv"
    write_review(path, [ReviewRow(1, "chat", 1, "unknown-player", "a\tb\nc")])
    written = write_review(path, [])
    assert written == 0
    assert path.read_text(encoding="utf-8") == "pass\tsource\tordinal\tcode\ttoken\n"

    write_review(path, [ReviewRow(1, "chat", 1, "unknown-player", "a\tb\nc")])
    assert path.read_text(encoding="utf-8").splitlines()[1].endswith("\ta b c")


def test_write_review_creates_the_directory(tmp_path: Path) -> None:
    path = tmp_path / "backfill" / "2025-review.tsv"
    write_review(path, [])
    assert path.exists()
```

```python
# add to packages/league-automation/tests/trades/test_resolve.py
def test_unresolved_carries_a_review_code_and_the_token_that_failed() -> None:
    """Every raise site says what kind of problem it is, so the review file can
    be written without matching prose."""
    with pytest.raises(Unresolved) as info:
        _resolve_player("Nobody Atall", [])
    assert info.value.code == "unknown-player" and info.value.token == "Nobody Atall"

    members = [MemberRef(1, "Ben", ("Big Ben",)), MemberRef(2, "Benjamin", ("Big Ben",))]
    with pytest.raises(Unresolved) as ambiguous:
        resolve_extracted(two_party_extraction(party="Big Ben"), members, [],
                          RosterIndex.empty(), 2025, "g", "x", "2026.1", "m")
    assert ambiguous.value.code == "ambiguous-member" and ambiguous.value.token == "Big Ben"

    with pytest.raises(Unresolved) as invalid:
        validate(one_party_proposal())
    assert invalid.value.code == "invalid" and invalid.value.token is None
```

Reuse the fixtures already in `tests/trades/test_resolve.py` for `two_party_extraction` and `one_party_proposal`; if they do not exist under those names, build the `ExtractedTrade` and `TradeProposal` inline the way the neighbouring tests in that file do.

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_review.py packages/league-automation/tests/trades/test_resolve.py -v`

Expected: FAIL — `Unresolved.__init__` takes one argument and `ultimate_guillotine.history.review` does not exist.

- [ ] **Step 3: Give `Unresolved` a code and a token**

```python
# packages/league-automation/src/ultimate_guillotine/trades/resolve.py
#: What kind of thing stopped a row, for a reviewer working through a backfill.
#: ``ambiguous-member`` and ``unknown-player`` name a token an alias can fix;
#: ``unclear`` and ``invalid`` are about the announcement itself.
REVIEW_CODES = ("ambiguous-member", "unknown-player", "unclear", "invalid")


class Unresolved(Exception):
    """Raised when a trade can't be resolved or validated without a human.

    ``reason`` is the sentence the registrar would ask the chat, and it quotes
    the announcement -- so batch tooling reports ``code`` and ``token``
    instead, which are a fixed vocabulary and one name.
    """

    def __init__(self, reason: str, code: str = "unclear", token: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code
        self.token = token
```

Then tag every existing raise site, changing nothing about the messages:

- `_resolve_player`, both raises: `code="unknown-player", token=name`.
- `resolve_member`, both raises (`I don't recognize ...` and `Two members go by ...`): `code="ambiguous-member", token=name`. An unrecognized nickname and an ambiguous one are the same repair — write an alias — so they share a code.
- `resolve_extracted`'s `kind == "unclear"` raise: leave it at the default `code="unclear"`, no token; the model's sentence is about the message.
- Every raise in `validate`: `code="invalid"`, no token; those four sentences are a fixed vocabulary with nothing quoted from the message.
- `cli/trades.py`'s `NOT_A_TRADE = Unresolved("not a trade")` sentinel is unchanged and keeps the default code.

- [ ] **Step 4: Implement the review file**

```python
# packages/league-automation/src/ultimate_guillotine/history/review.py
"""The list of rows a backfill could not resolve, for Ben to work through.

Deliberately thin. A review line is a pointer -- which pass, which source,
which row -- plus the fixed-vocabulary code and the one token an alias would be
written against. No message text, no chat GUID, no candidate list, no model
prose: everything a reviewer needs is either in the line or one ``ug members
list`` away, and everything else would be a copy of the league's private chat
sitting in a file.

The file is rewritten from scratch every run, so a rerun after an alias fix
shrinks it visibly. It lives under ``data/private/``, which is git-ignored.
"""

from dataclasses import dataclass
from pathlib import Path

from ultimate_guillotine.trades.resolve import Unresolved

HEADER = "pass\tsource\tordinal\tcode\ttoken"
DEFAULT_ROOT = Path("data/private/backfill")
#: Codes whose token would be model prose about the message rather than a name.
_TOKENLESS = {"unclear", "invalid"}


@dataclass(frozen=True)
class ReviewRow:
    pass_number: int
    source: str
    ordinal: int
    code: str
    token: str


def review_path(season: int, root: Path = DEFAULT_ROOT) -> Path:
    return root / f"{season}-review.tsv"


def review_row(pass_number: int, source: str, ordinal: int, exc: Unresolved) -> ReviewRow:
    token = "" if exc.code in _TOKENLESS or exc.token is None else exc.token
    return ReviewRow(pass_number, source, ordinal, exc.code, _flatten(token))


def write_review(path: Path, rows: list[ReviewRow]) -> int:
    """Replace ``path`` with ``rows``, returning how many were written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [HEADER]
    lines += [
        f"{r.pass_number}\t{r.source}\t{r.ordinal}\t{r.code}\t{_flatten(r.token)}" for r in rows
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def _flatten(token: str) -> str:
    """Collapse whitespace so one row is always one line and five fields."""
    return " ".join(token.split())
```

- [ ] **Step 5: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation
git commit -m "feat: classify unresolved rows and write a backfill review file"
```

---

### Task 6: Candidates from both sources, in chronological order

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/trades.py` (`load_contract_rows`)
- Create: `packages/league-automation/src/ultimate_guillotine/history/candidates.py`
- Create: `packages/league-automation/tests/history/test_candidates.py`
- Modify: `packages/league-automation/tests/cli/test_trades_replay.py`

**Interfaces:**
- Consumes: `is_trade_candidate`, `ALERT`, `season_window`, `SEASON_TZ`, `InboundMessage`, `openpyxl`.
- Produces:
  - `cli/trades.py`: `@dataclass(frozen=True) class ContractRow: date: str; week: str; text: str; parties: tuple[str, ...]` and `load_contract_rows(path) -> list[ContractRow]`; `load_replay_rows` becomes a three-line adapter over it and keeps its exact current return shape.
  - `history/candidates.py`: `@dataclass(frozen=True) class Candidate: source: str; ordinal: int; source_guid: str; text: str; sent_at: datetime; week: int | None`,
    `chat_candidates(messages: Iterable[InboundMessage]) -> tuple[list[Candidate], int]`,
    `xlsx_candidates(rows: list[ContractRow], season: int) -> list[Candidate]`,
    `sheet_row_time(date_text: str, week_text: str, season: int) -> datetime`,
    `week_number(week_text: str) -> int | None`,
    `order_candidates(candidates: list[Candidate]) -> list[Candidate]`

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/history/test_candidates.py
from datetime import UTC, datetime

from ultimate_guillotine.cli.trades import ContractRow
from ultimate_guillotine.history.archive import SEASON_TZ
from ultimate_guillotine.history.candidates import (
    chat_candidates,
    order_candidates,
    sheet_row_time,
    week_number,
    xlsx_candidates,
)
from ultimate_guillotine.messages.bluebubbles import InboundMessage

ALERT_TEXT = "🚨 Trade Alert 🚨 Member01 sends Player Alpha to Member02 for 100 FAAB"


def msg(guid: str, text: str, when: datetime) -> InboundMessage:
    return InboundMessage(guid=guid, chat_guid="c", sender_address="+15555550100", text=text,
                          is_from_me=False, is_group=True, sent_at=when)


def test_chat_candidates_keep_alerts_count_everything_and_number_by_scan_position() -> None:
    when = datetime(2025, 10, 1, tzinfo=UTC)
    messages = [msg("g1", "lol", when), msg("g2", ALERT_TEXT, when), msg("g3", "nice", when)]
    candidates, scanned = chat_candidates(messages)
    assert scanned == 3
    assert [(c.ordinal, c.source, c.source_guid) for c in candidates] == [(2, "chat", "g2")]
    assert candidates[0].text == ALERT_TEXT and candidates[0].week is None


def test_xlsx_candidates_get_a_non_guid_shaped_id_and_the_siren_back() -> None:
    rows = [ContractRow("2025-09-25", "Week 3", f"🚨 {'Member01 sends Player Alpha'}", ())]
    candidates = xlsx_candidates(rows, 2025)
    assert candidates[0].source == "xlsx"
    assert candidates[0].source_guid == "xlsx:2025:row-1"
    assert candidates[0].week == 3
    assert candidates[0].sent_at == datetime(2025, 9, 25, tzinfo=SEASON_TZ)


def test_sheet_row_time_falls_back_to_the_week_when_the_date_cell_is_unusable() -> None:
    start = datetime(2025, 8, 1, tzinfo=SEASON_TZ)
    assert sheet_row_time("", "Week 1", 2025) == start
    assert sheet_row_time("not a date", "Week 3", 2025) == start.replace(day=15)
    # Neither a date nor a week: the row still needs a place in the season.
    assert sheet_row_time("", "", 2025) == start


def test_sheet_row_time_clamps_a_date_outside_the_season_into_it() -> None:
    assert sheet_row_time("2019-01-01", "Week 2", 2025) == datetime(2025, 8, 8, tzinfo=SEASON_TZ)


def test_week_number_reads_the_digits_and_gives_up_quietly() -> None:
    assert week_number("Week 12") == 12 and week_number("3") == 3
    assert week_number("Preseason") is None and week_number("") is None


def test_order_candidates_sorts_by_message_time_then_ordinal() -> None:
    early, late = datetime(2025, 9, 1, tzinfo=UTC), datetime(2025, 11, 1, tzinfo=UTC)
    out = order_candidates([
        *xlsx_candidates([ContractRow("2025-11-01", "Week 9", "🚨 b", ())], 2025),
        *chat_candidates([msg("g1", ALERT_TEXT, late), msg("g2", ALERT_TEXT, early)])[0],
    ])
    assert [c.sent_at for c in out] == sorted(c.sent_at for c in out)
    assert out[0].source_guid == "g2"
```

```python
# add to packages/league-automation/tests/cli/test_trades_replay.py
def test_load_contract_rows_keeps_the_date_column(tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Date", "Week", "Terms", "Parties"])
    ws.append(["2025-09-07", "Week 1", TERMS, "Member01", "Member02"])
    path = tmp_path / "c.xlsx"
    wb.save(path)

    rows = load_contract_rows(path)

    assert rows == [ContractRow("2025-09-07", "Week 1", f"🚨 {TERMS}", ("Member01", "Member02"))]
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_candidates.py packages/league-automation/tests/cli/test_trades_replay.py -v`

Expected: FAIL — `ContractRow` and `load_contract_rows` are not defined.

- [ ] **Step 3: Split the workbook loader without changing what replay sees**

In `cli/trades.py`, add `DATE_COLUMN = 0` beside the existing column constants, and:

```python
@dataclass(frozen=True)
class ContractRow:
    """One trade row of the contracts spreadsheet, siren restored.

    ``date`` and ``week`` are kept as the sheet's own strings: the sheet is
    hand-maintained and its date cells are sometimes a date, sometimes prose,
    sometimes empty, and deciding what a row's timestamp is belongs to the
    caller that knows which season it is loading.
    """

    date: str
    week: str
    text: str
    parties: tuple[str, ...]


def load_contract_rows(path: str | Path) -> list[ContractRow]:
    """Read every trade row out of a contracts spreadsheet.

    (Move the existing `load_replay_rows` body here unchanged, building a
    `ContractRow` with `_cell(row, DATE_COLUMN)` as `date` and the parties as a
    tuple; keep the docstring about merged cells and uncached formulas.)
    """


def load_replay_rows(path: str | Path) -> list[tuple[str, str, list[str]]]:
    """`(week, alert text, parties)` for `ug trades replay`, which needs no dates."""
    return [(row.week, row.text, list(row.parties)) for row in load_contract_rows(path)]
```

- [ ] **Step 4: Implement the candidate builders**

```python
# packages/league-automation/src/ultimate_guillotine/history/candidates.py
"""One row of history, from either source, with a time it can be sorted by.

Detection happens here, once, on the way in: a message that is not a trade
candidate is counted and dropped in memory and never reaches the model, the
database, or this process's memory beyond a counter. That is what keeps tens of
thousands of chat messages out of Supabase.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ultimate_guillotine.history.archive import SEASON_TZ, season_window
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.trades.detect import is_trade_candidate

_WEEK_DIGITS = re.compile(r"\d+")


@dataclass(frozen=True)
class Candidate:
    """A row worth spending a model call on.

    ``ordinal`` is the row's position in its source -- the message's place in
    the scan, or the workbook row -- so a review line points at something a
    human can go and look at without the text being written down.
    """

    source: str
    ordinal: int
    source_guid: str
    text: str
    sent_at: datetime
    week: int | None


def chat_candidates(messages: Iterable[InboundMessage]) -> tuple[list[Candidate], int]:
    """Alert-shaped messages, plus how many messages were looked at in total."""
    candidates: list[Candidate] = []
    scanned = 0
    for ordinal, message in enumerate(messages, start=1):
        scanned = ordinal
        if not is_trade_candidate(message.text):
            continue
        candidates.append(
            Candidate("chat", ordinal, message.guid, message.text, message.sent_at, None)
        )
    return candidates, scanned


def xlsx_candidates(rows: list, season: int) -> list[Candidate]:
    """Spreadsheet rows as candidates, with ids that are deliberately not GUIDs.

    ``xlsx:<season>:row-<n>`` can never be mistaken for an Apple message GUID,
    which is the point: a revision carrying one is a hand transcription, not
    something the league announced.
    """
    return [
        Candidate(
            "xlsx",
            index,
            f"xlsx:{season}:row-{index}",
            row.text,
            sheet_row_time(row.date, row.week, season),
            week_number(row.week),
        )
        for index, row in enumerate(rows, start=1)
        if is_trade_candidate(row.text)
    ]


def week_number(week_text: str) -> int | None:
    match = _WEEK_DIGITS.search(week_text or "")
    return int(match.group(0)) if match else None


def sheet_row_time(date_text: str, week_text: str, season: int) -> datetime:
    """When a ledger row happened, in league time.

    The sheet's date wins. Failing that, the week is placed seven days per week
    from the season's start, which is enough to order the row against the chat
    and to hold it inside the season. A date outside the season is clamped into
    it rather than dropped: a mistyped year in one cell must not put a 2025
    trade in another season's window.
    """
    start, end = season_window(season)
    when: datetime | None = None
    head = (date_text or "").strip().split(" ")[0]
    if head:
        try:
            when = datetime.fromisoformat(head).replace(tzinfo=SEASON_TZ)
        except ValueError:
            when = None
    if when is None:
        when = start + timedelta(days=7 * ((week_number(week_text) or 1) - 1))
    if when < start:
        return start
    return min(when, end - timedelta(seconds=1))


def order_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Oldest first. Trade codes are allocated in insertion order, so this is
    what makes ``T-2025-001`` the season's first trade rather than its first row."""
    return sorted(candidates, key=lambda c: (c.sent_at, c.ordinal))
```

- [ ] **Step 5: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

Expected: PASS, including the existing `test_load_replay_rows_reads_terms_and_parties`, which must be untouched.

```bash
git add packages/league-automation
git commit -m "feat: build ordered backfill candidates from chat and spreadsheet"
```

---

### Task 7: Run keys that skip finished rows and retry unfinished ones

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/data/repositories.py`
- Create: `packages/league-automation/src/ultimate_guillotine/history/runkeys.py`
- Create: `packages/league-automation/tests/history/test_runkeys.py`
- Modify: `packages/league-automation/tests/data/test_repositories.py`

**Interfaces:**
- Consumes: `RunRepository.reserve/.finish`.
- Produces:
  - `RunRepository.status_for(idempotency_key: str) -> str | None` — the newest run whose key is `idempotency_key` or starts with `<key>:retry:`
  - `history/runkeys.py`: `BACKFILL_AGENT = "trade-history-backfill"`, `TRIGGER = "backfill"`, `FINISHED = ("succeeded", "duplicate")`,
    `backfill_key(season: int, source_guid: str) -> str`,
    `reserve_row(runs, season: int, source_guid: str, now: datetime) -> int | None`

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/history/test_runkeys.py
from datetime import UTC, datetime

from ultimate_guillotine.history.runkeys import BACKFILL_AGENT, backfill_key, reserve_row

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class FakeRuns:
    def __init__(self, status: str | None = None) -> None:
        self.status, self.reserved = status, []

    def status_for(self, key: str) -> str | None:
        return self.status

    def reserve(self, agent, trigger, key, invoked_by=None):
        self.reserved.append((agent, trigger, key))
        return len(self.reserved)


def test_key_names_the_backfill_the_season_and_the_row() -> None:
    assert backfill_key(2025, "p:0/ABC") == "trade:backfill:2025:p:0/ABC"


def test_a_fresh_row_reserves_the_plain_key() -> None:
    runs = FakeRuns(None)
    assert reserve_row(runs, 2025, "g1", NOW) == 1
    assert runs.reserved == [(BACKFILL_AGENT, "backfill", "trade:backfill:2025:g1")]


def test_a_finished_row_is_skipped_without_reserving_anything() -> None:
    for status in ("succeeded", "duplicate"):
        runs = FakeRuns(status)
        assert reserve_row(runs, 2025, "g1", NOW) is None
        assert runs.reserved == []


def test_a_failed_or_abandoned_row_reserves_a_per_attempt_key() -> None:
    for status in ("failed", "running"):
        runs = FakeRuns(status)
        assert reserve_row(runs, 2025, "g1", NOW) == 1
        assert runs.reserved[0][2] == f"trade:backfill:2025:g1:retry:{int(NOW.timestamp())}"
```

```python
# add to packages/league-automation/tests/data/test_repositories.py
def test_status_for_finds_the_newest_attempt_including_retries(conn) -> None:
    runs = RunRepository(conn)
    key = "trade:backfill:2025:g1"
    assert runs.status_for(key) is None
    first = runs.reserve("a", "backfill", key)
    runs.finish(first, "failed", error="ambiguous-member")
    assert runs.status_for(key) == "failed"
    second = runs.reserve("a", "backfill", f"{key}:retry:1")
    runs.finish(second, "succeeded")
    assert runs.status_for(key) == "succeeded"
    # A different row's key is never picked up by the prefix match.
    assert runs.status_for("trade:backfill:2025:g2") is None
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_runkeys.py -v`

Expected: FAIL — `ultimate_guillotine.history.runkeys` does not exist.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/data/repositories.py, in RunRepository
    def status_for(self, idempotency_key: str) -> str | None:
        """The status of the newest run for this key, retries included.

        A batch that reruns itself has to tell "already done" from "tried and
        did not finish". ``starts_with`` rather than ``like`` because a key can
        carry an Apple message GUID, which may contain ``%`` or ``_``.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select status from private.agent_runs
                where idempotency_key = %s or starts_with(idempotency_key, %s)
                order by id desc limit 1
                """,
                (idempotency_key, f"{idempotency_key}:retry:"),
            )
            row = cur.fetchone()
            return row[0] if row else None
```

```python
# packages/league-automation/src/ultimate_guillotine/history/runkeys.py
"""Reservation keys for backfilled rows.

Deliberately unlike ``ug trades replay``, where a row that has run once is
``skipped`` forever. A backfill is rerun on purpose, after an alias fix, and a
row that stopped on an unresolvable name has to run again the next time round;
only a row that actually landed -- ``succeeded`` or ``duplicate`` -- is done.
``private.agent_runs.status`` has no ``clarification`` value, so an unresolved
row finishes ``failed`` with its review code in ``error``.
"""

from datetime import datetime

BACKFILL_AGENT = "trade-history-backfill"
TRIGGER = "backfill"
#: Statuses that mean this row is done and must never cost another model call.
FINISHED = ("succeeded", "duplicate")


def backfill_key(season: int, source_guid: str) -> str:
    return f"trade:backfill:{season}:{source_guid}"


def reserve_row(runs, season: int, source_guid: str, now: datetime) -> int | None:
    """Reserve a run for one row, or ``None`` when the row is already done."""
    key = backfill_key(season, source_guid)
    prior = runs.status_for(key)
    if prior in FINISHED:
        return None
    if prior is not None:
        key = f"{key}:retry:{int(now.timestamp())}"
    return runs.reserve(BACKFILL_AGENT, TRIGGER, key)
```

- [ ] **Step 4: Run green, lint, commit**

Run: `TEST_DATABASE_URL=... pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation
git commit -m "feat: add rerunnable run keys for backfilled rows"
```

---

### Task 8: The backfill runner

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/trades/pipeline.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/trades.py` (import the moved helpers)
- Create: `packages/league-automation/src/ultimate_guillotine/history/runner.py`
- Create: `packages/league-automation/tests/history/test_runner.py`
- Create: `packages/league-automation/tests/history/test_read_only.py`

**Interfaces:**
- Consumes: `Candidate`, `reserve_row`, `review_row`, `TradeRepository.accept/.rescind/.find_by_context/.find_by_id`, `SourceMessageRepository.upsert`, `RunRepository.finish`, `chat_guid_hash`, `message_fingerprint`, `trade_context_key`.
- Produces:
  - `trades/pipeline.py`: `NOT_A_TRADE`, `dry_run_pipeline(...)` (moved verbatim from `cli/trades.py`), `SUMMARY_FIXED`, `SUMMARY_EXTRA`, `summary_line(label: str, total: int, counts: dict[str, int]) -> str`
  - `history/runner.py`: `SEASON_SPAN_HOURS = 24 * 400`, `TRIGGER_NAME = "trade-alert-backfill"`, `EXCERPT_LIMIT = 2000`,
    `@dataclass(frozen=True) class RowOutcome: outcome: str; review: ReviewRow | None = None; trade_code: str | None = None`,
    `class BackfillRunner` with `__init__(ai, conn, season, chat_hash, members, players, rosters, trades, runs, sources, dry_run, clock)` and `run_row(candidate, pass_number) -> RowOutcome`, `run_pass(candidates, pass_number, label) -> dict[str, int]`

- [ ] **Step 1: Write the failing runner tests**

```python
# packages/league-automation/tests/history/test_runner.py
from datetime import UTC, datetime

from ultimate_guillotine.ai.openrouter import AIUsage
from ultimate_guillotine.history.candidates import Candidate
from ultimate_guillotine.history.runner import SEASON_SPAN_HOURS, BackfillRunner
from ultimate_guillotine.trades.models import (
    ExtractedAsset,
    ExtractedParty,
    ExtractedTrade,
    MemberRef,
    TradeAsset,
    TradeParty,
)
from ultimate_guillotine.trades.repository import TradeAcceptance
from ultimate_guillotine.sleeper.players import Player

WEEK3 = datetime(2025, 9, 25, tzinfo=UTC)
NOW = datetime(2026, 9, 9, tzinfo=UTC)


def extraction(faab: int = 100) -> ExtractedTrade:
    return ExtractedTrade(
        kind="permanent",
        parties=[ExtractedParty(name="Member01"), ExtractedParty(name="Member02")],
        assets=[
            ExtractedAsset(kind="player", from_party="Member01", to_party="Member02",
                           player_name="Player Alpha"),
            ExtractedAsset(kind="faab", from_party="Member02", to_party="Member01",
                           amount=faab, unit="faab"),
        ],
    )


class FakeAI:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error, self.calls = result, error, 0

    def parse(self, system, user, schema, name):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result, AIUsage("gen", 1, 1, "hermes-model")


class FakeRuns:
    def __init__(self, status=None) -> None:
        self.status, self.reserved, self.finished = status, [], []

    def status_for(self, key):
        return self.status

    def reserve(self, agent, trigger, key, invoked_by=None):
        self.reserved.append(key)
        return len(self.reserved)

    def finish(self, run_id, status, output_hash=None, error=None, input_version=None):
        self.finished.append((run_id, status, error))


class FakeTrades:
    def __init__(self, status="created") -> None:
        self.status, self.calls, self.rescinded = status, [], []

    def accept(self, proposal, occurred_at=None, revise_within_hours=72):
        self.calls.append((proposal, occurred_at, revise_within_hours))
        return TradeAcceptance(self.status, 7, "T-2025-001", 1, None)

    def find_by_context(self, key, within_hours=72):
        return None

    def rescind(self, code, source_guid, occurred_at):
        self.rescinded.append((code, occurred_at))
        return True


class FakeSources:
    def __init__(self) -> None:
        self.rows = []

    def upsert(self, msg) -> bool:
        self.rows.append(msg)
        return True


class FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


def build(ai, trades=None, runs=None, sources=None, dry_run=False):
    return BackfillRunner(
        ai=ai, conn=FakeConn(), season=2025, chat_hash="hash",
        members=[MemberRef(1, "Member01", ()), MemberRef(2, "Member02", ())],
        players=[Player("p1", "Player Alpha", "WR", "KC", True)],
        rosters=None, trades=trades or FakeTrades(), runs=runs or FakeRuns(),
        sources=sources or FakeSources(), dry_run=dry_run, clock=lambda: NOW,
    )


def chat_row(guid: str = "g1") -> Candidate:
    return Candidate("chat", 132, guid, "🚨 Member01 sends Player Alpha to Member02 for 100 FAAB",
                     WEEK3, None)


def sheet_row() -> Candidate:
    return Candidate("xlsx", 14, "xlsx:2025:row-14",
                     "🚨 Member01 sends Player Alpha to Member02 for 100 FAAB", WEEK3, 3)


def test_a_chat_row_is_accepted_at_its_message_time_and_recorded_as_a_source() -> None:
    trades, sources = FakeTrades(), FakeSources()
    runner = build(FakeAI(extraction()), trades=trades, sources=sources)
    result = runner.run_row(chat_row(), pass_number=1)
    assert result.outcome == "created" and result.trade_code == "T-2025-001"
    proposal, occurred_at, window = trades.calls[0]
    assert occurred_at == WEEK3 and window == 72
    assert proposal.source_message_guid == "g1" and proposal.source is None
    recorded = sources.rows[0]
    assert recorded.trigger_name == "trade-alert-backfill"
    assert recorded.sender_hash is None and recorded.direction == "inbound"
    assert recorded.sent_at == WEEK3 and recorded.chat_guid_hash == "hash"
    assert len(recorded.excerpt) <= 2000


def test_a_spreadsheet_row_is_marked_and_may_revise_across_the_whole_season() -> None:
    trades = FakeTrades("revised")
    runner = build(FakeAI(extraction(200)), trades=trades, sources=FakeSources())
    result = runner.run_row(sheet_row(), pass_number=2)
    assert result.outcome == "revised"
    proposal, _occurred_at, window = trades.calls[0]
    assert window == SEASON_SPAN_HOURS
    assert proposal.source == "contracts-xlsx"
    assert proposal.source_message_guid == "xlsx:2025:row-14"


def test_a_spreadsheet_row_is_never_written_to_private_source_messages() -> None:
    sources = FakeSources()
    runner = build(FakeAI(extraction()), sources=sources)
    runner.run_row(sheet_row(), pass_number=2)
    assert sources.rows == []


def test_an_unresolved_row_produces_a_review_line_and_finishes_failed() -> None:
    runs = FakeRuns()
    unknown = extraction().model_copy(update={
        "assets": [ExtractedAsset(kind="player", from_party="Member01", to_party="Member02",
                                  player_name="Retired Player")]
    })
    runner = build(FakeAI(unknown), runs=runs)
    result = runner.run_row(chat_row(), pass_number=1)
    assert result.outcome == "clarification: unknown-player"
    assert result.review.code == "unknown-player" and result.review.token == "Retired Player"
    assert result.review.pass_number == 1 and result.review.ordinal == 132
    assert runs.finished[0][1] == "failed" and runs.finished[0][2] == "unknown-player"


def test_a_finished_row_is_skipped_before_the_model_is_called() -> None:
    ai = FakeAI(extraction())
    runner = build(ai, runs=FakeRuns("succeeded"))
    assert runner.run_row(chat_row(), pass_number=1).outcome == "skipped"
    assert ai.calls == 0


def test_a_row_the_model_reads_as_chatter_is_recorded_and_says_nothing() -> None:
    runs, sources = FakeRuns(), FakeSources()
    joke = extraction().model_copy(update={"kind": "not_a_trade", "parties": [], "assets": []})
    runner = build(FakeAI(joke), runs=runs, sources=sources)
    assert runner.run_row(chat_row(), pass_number=1).outcome == "not-a-trade"
    assert sources.rows == [] and runs.finished[0][1] == "succeeded"


def test_a_rescission_rescinds_the_trade_its_context_names() -> None:
    class Rescinding(FakeTrades):
        def find_by_context(self, key, within_hours=72):
            assert within_hours == SEASON_SPAN_HOURS
            return 7

        def find_by_id(self, trade_id):
            return {"trade_code": "T-2025-004"}

    trades = Rescinding()
    rescission = extraction().model_copy(update={"kind": "rescission"})
    runner = build(FakeAI(rescission), trades=trades)
    result = runner.run_row(chat_row(), pass_number=1)
    assert result.outcome == "rescinded" and trades.rescinded == [("T-2025-004", WEEK3)]


def test_a_dry_run_reserves_nothing_writes_nothing_and_still_reviews() -> None:
    trades, runs, sources = FakeTrades(), FakeRuns(), FakeSources()
    runner = build(FakeAI(extraction()), trades=trades, runs=runs, sources=sources, dry_run=True)
    assert runner.run_row(chat_row(), pass_number=1).outcome == "created"
    assert trades.calls == [] and runs.reserved == [] and sources.rows == []


def test_a_failing_row_is_reported_and_does_not_stop_the_pass() -> None:
    from ultimate_guillotine.ai.openrouter import AIUnavailable
    runs = FakeRuns()
    runner = build(FakeAI(error=AIUnavailable("down")), runs=runs)
    result = runner.run_row(chat_row(), pass_number=1)
    assert result.outcome == "failed" and runs.finished[0][1] == "failed"
    assert runs.finished[0][2] == "AIUnavailable"


def test_run_pass_prints_one_line_per_row_and_counts_them(capsys) -> None:
    runner = build(FakeAI(extraction()))
    counts = runner.run_pass([chat_row("g1"), chat_row("g2")], pass_number=1, label="chat")
    assert counts["created"] == 2
    out = capsys.readouterr().out
    assert out.startswith("chat 132: created\n")
    assert "backfill chat: 2 rows" in out
```

- [ ] **Step 2: Write the failing read-only test**

```python
# packages/league-automation/tests/history/test_read_only.py
from pathlib import Path

import ultimate_guillotine.history as history

#: Anything that could put a message into the chat. The backfill reads an
#: archive; a send in this package would be a bug nobody would notice until the
#: league received a years-old trade confirmation.
FORBIDDEN = ("DeliveryService", "send_text", "/api/v1/message", "ensure_webhook")


def test_the_history_package_cannot_send_anything() -> None:
    for path in sorted(Path(history.__file__).parent.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            assert needle not in text, f"{path.name} names {needle}"
```

- [ ] **Step 3: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history -v`

Expected: FAIL — `ultimate_guillotine.history.runner` does not exist.

- [ ] **Step 4: Move the pipeline helpers**

Create `trades/pipeline.py` holding `NOT_A_TRADE`, `dry_run_pipeline`, `SUMMARY_FIXED`, `SUMMARY_EXTRA` moved verbatim from `cli/trades.py`, plus:

```python
def summary_line(label: str, total: int, counts: dict[str, int]) -> str:
    """The closing line of a batch: the fixed counters always, the rest if they
    happened, so the numbers always add up to the row count."""
    parts = [f"{name} {counts[name]}" for name in SUMMARY_FIXED]
    parts += [f"{name} {counts[name]}" for name in SUMMARY_EXTRA if counts[name]]
    return f"{label}: {total} rows, " + ", ".join(parts)
```

`cli/trades.py` imports all five names from `ultimate_guillotine.trades.pipeline` and re-exports them (the existing tests import `dry_run_pipeline` and `NOT_A_TRADE` from `cli.trades`), and `replay_rows` ends with `print(summary_line("replay", total, counts))`. Its exact-output test must still pass unchanged.

- [ ] **Step 5: Implement the runner**

```python
# packages/league-automation/src/ultimate_guillotine/history/runner.py
"""One backfilled row at a time, and one pass over many of them.

This is the Registrar's pipeline with the clock moved and the mouth removed. It
calls the same detection, the same single model call, the same deterministic
resolution and the same ``TradeRepository`` -- but it constructs no
``TradeRegistrar``, no ``DeliveryService`` and no notifier, so there is no code
path from here to the league chat, whatever ``DELIVERY_MODE`` says. Failures
are printed, never posted: a past season fails on rows nobody is going to fix,
and paging ``#guillotine-alerts`` for each of them would be noise about history.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from ultimate_guillotine.data.repositories import SourceMessage
from ultimate_guillotine.history.candidates import Candidate
from ultimate_guillotine.history.review import ReviewRow, review_row
from ultimate_guillotine.history.runkeys import reserve_row
from ultimate_guillotine.messages.fingerprint import message_fingerprint
from ultimate_guillotine.trades.fingerprint import trade_context_key
from ultimate_guillotine.trades.pipeline import NOT_A_TRADE, dry_run_pipeline, summary_line
from ultimate_guillotine.trades.resolve import Unresolved

#: How far back a ledger row may reach to find the alert it corrects: further
#: than any one season, so a match never depends on when the rows were written.
SEASON_SPAN_HOURS = 24 * 400
#: How far back a chat row may reach. The live window, unchanged: message times
#: are real here, so a repost hours later revises and a new deal weeks later
#: does not.
CHAT_WINDOW_HOURS = 72
TRIGGER_NAME = "trade-alert-backfill"
EXCERPT_LIMIT = 2000
SOURCE_XLSX = "contracts-xlsx"


@dataclass(frozen=True)
class RowOutcome:
    outcome: str
    review: ReviewRow | None = None
    trade_code: str | None = None


class BackfillRunner:
    def __init__(
        self, ai, conn, season: int, chat_hash: str, members, players, rosters,
        trades, runs, sources, dry_run: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ai = ai
        self._conn = conn
        self._season = season
        self._chat_hash = chat_hash
        self._members = members
        self._players = players
        self._rosters = rosters
        self._trades = trades
        self._runs = runs
        self._sources = sources
        self._dry_run = dry_run
        self._clock = clock

    def run_row(self, candidate: Candidate, pass_number: int) -> RowOutcome:
        run_id = None
        if not self._dry_run:
            run_id = reserve_row(self._runs, self._season, candidate.source_guid, self._clock())
            if run_id is None:
                return RowOutcome("skipped")
            self._commit()
        try:
            return self._process(run_id, candidate, pass_number)
        except Exception as exc:  # noqa: BLE001 - every failure is reported the same way
            self._rollback()
            self._finish(run_id, "failed", error=exc.__class__.__name__)
            return RowOutcome("failed")

    def run_pass(self, candidates: list[Candidate], pass_number: int, label: str) -> dict:
        """Run one source's candidates in order, printing a line each and a summary.

        The line carries the review code, never the model's sentence: the
        sentence quotes the announcement, and this output is read over a
        shoulder and pasted into notes.
        """
        from ultimate_guillotine.trades.pipeline import SUMMARY_EXTRA, SUMMARY_FIXED

        counts = dict.fromkeys(SUMMARY_FIXED + SUMMARY_EXTRA, 0)
        self.reviews: list[ReviewRow] = getattr(self, "reviews", [])
        self.outcomes: list[tuple[Candidate, RowOutcome]] = getattr(self, "outcomes", [])
        total = 0
        for total, candidate in enumerate(candidates, start=1):
            result = self.run_row(candidate, pass_number)
            print(f"{label} {candidate.ordinal}: {result.outcome}")
            head = result.outcome.split(":", 1)[0].strip()
            if head in counts:
                counts[head] += 1
            if result.review is not None:
                self.reviews.append(result.review)
            self.outcomes.append((candidate, result))
        print(summary_line(f"backfill {label}", total, counts))
        return counts

    # -- internals ------------------------------------------------------

    def _process(self, run_id, candidate: Candidate, pass_number: int) -> RowOutcome:
        result = dry_run_pipeline(
            self._ai, candidate.text, self._season, self._members, self._players,
            self._rosters, candidate.source_guid,
        )
        if result is NOT_A_TRADE:
            self._finish(run_id, "succeeded")
            return RowOutcome("not-a-trade")
        if isinstance(result, Unresolved):
            review = review_row(pass_number, candidate.source, candidate.ordinal, result)
            # `private.agent_runs.status` has no `clarification`: the row did not
            # land, so it is `failed`, and the code is the reason it failed.
            self._finish(run_id, "failed", error=result.code)
            return RowOutcome(f"clarification: {result.code}", review=review)

        proposal = result
        if candidate.source == "xlsx":
            proposal = proposal.model_copy(update={"source": SOURCE_XLSX})
        if proposal.kind == "rescission":
            return self._rescind(run_id, candidate, proposal, pass_number)
        if self._dry_run:
            return RowOutcome("created")

        window = SEASON_SPAN_HOURS if candidate.source == "xlsx" else CHAT_WINDOW_HOURS
        acceptance = self._trades.accept(
            proposal, occurred_at=candidate.sent_at, revise_within_hours=window
        )
        if acceptance.status != "duplicate" and candidate.source == "chat":
            self._record_source(candidate)
        self._finish(
            run_id,
            "duplicate" if acceptance.status == "duplicate" else "succeeded",
            input_version=f"{proposal.prompt_version}:{proposal.model}",
        )
        return RowOutcome(acceptance.status, trade_code=acceptance.trade_code)

    def _rescind(self, run_id, candidate: Candidate, proposal, pass_number: int) -> RowOutcome:
        """Rescissions collapse into the trade they kill rather than becoming one.

        The archive holds them, and a rescission accepted as a trade would give
        the Advisor a deal that never happened.
        """
        if self._dry_run:
            return RowOutcome("rescinded")
        trade_id = self._trades.find_by_context(
            trade_context_key(proposal), within_hours=SEASON_SPAN_HOURS
        )
        trade = self._trades.find_by_id(trade_id) if trade_id is not None else None
        if trade is None:
            review = review_row(
                pass_number, candidate.source, candidate.ordinal,
                Unresolved("no trade to rescind", code="unclear"),
            )
            self._finish(run_id, "failed", error="unclear")
            return RowOutcome("clarification: unclear", review=review)
        self._trades.rescind(trade["trade_code"], candidate.source_guid, candidate.sent_at)
        if candidate.source == "chat":
            self._record_source(candidate)
        self._finish(run_id, "succeeded")
        return RowOutcome("rescinded", trade_code=trade["trade_code"])

    def _record_source(self, candidate: Candidate) -> None:
        """One evidence row per accepted chat candidate, and nothing else.

        ``sender_hash`` is null on purpose: the parties come from the text, and
        a backfill has no reason to keep a per-sender identity for a message
        from four years ago.
        """
        self._sources.upsert(SourceMessage(
            source_guid=candidate.source_guid,
            chat_guid_hash=self._chat_hash,
            sender_hash=None,
            direction="inbound",
            sent_at=candidate.sent_at,
            content_fingerprint=message_fingerprint(candidate.text),
            excerpt=candidate.text[:EXCERPT_LIMIT],
            trigger_name=TRIGGER_NAME,
        ))

    def _finish(self, run_id, status: str, error: str | None = None,
                input_version: str | None = None) -> None:
        if run_id is None:
            return
        self._runs.finish(run_id, status, error=error, input_version=input_version)
        self._commit()

    def _commit(self) -> None:
        if self._conn is not None and not self._dry_run:
            self._conn.commit()

    def _rollback(self) -> None:
        if self._conn is not None:
            try:
                self._conn.rollback()
            except Exception:  # noqa: BLE001 - a dead connection must still report
                pass
```

Move the `reviews`/`outcomes` lists into `__init__` while implementing rather than the `getattr` default shown above; they are declared here only so the fields are visible in one place. `run_pass` returns the counts and leaves the collected reviews and outcomes on the runner for the CLI to write and report.

- [ ] **Step 6: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation
git commit -m "feat: add the league history backfill runner"
```

---

### Task 9: `ug trades backfill`

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/trades.py`
- Create: `packages/league-automation/tests/cli/test_trades_backfill.py`
- Modify: `packages/league-automation/tests/cli/test_trades.py`

**Interfaces:**
- Consumes: everything produced by Tasks 1–8, plus `build_deps`, `build_ai`, `load_settings`, `TargetRepository`, `SeasonRepository`, `MemberAliasRepository`, `PlayerRepository`, `code_prefix_for`.
- Produces: `ug trades backfill --season Y --source chat|xlsx|both [--xlsx PATH] [--chat-name NAME] [--expected-rosters N] [--dry-run] [--limit N]`, and `cmd_backfill(args) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/cli/test_trades_backfill.py
import argparse
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import trades as trades_cli
from ultimate_guillotine.config import Settings


def args(**overrides) -> argparse.Namespace:
    base = dict(season=2025, source="chat", xlsx=None, chat_name=None,
                expected_rosters=None, dry_run=True, limit=None)
    base.update(overrides)
    return argparse.Namespace(**base)


def settings(mode: str = "disabled") -> Settings:
    return Settings(database_url="postgresql://x:y@example.invalid/db", delivery_mode=mode,
                    production_chat_guid="g" if mode == "production" else None,
                    production_participant_fingerprint="f" if mode == "production" else None,
                    openrouter_api_key="sk-test", _env_file=None)


def test_backfill_refuses_production_before_opening_a_connection(monkeypatch, capsys) -> None:
    monkeypatch.setattr(trades_cli, "load_settings", lambda: settings("production"))
    monkeypatch.setattr(trades_cli, "build_deps", lambda: pytest.fail("must not connect"))
    assert trades_cli.cmd_backfill(args(dry_run=False)) == 2
    assert "production" in capsys.readouterr().out


def test_backfill_refuses_the_current_season(monkeypatch, capsys) -> None:
    monkeypatch.setattr(trades_cli, "load_settings", lambda: settings())
    monkeypatch.setattr(trades_cli, "build_deps", lambda: SimpleNamespace(
        settings=settings(), conn=object(), client=object(), notifier=None))
    monkeypatch.setattr(trades_cli, "current_season", lambda _conn: 2025)
    assert trades_cli.cmd_backfill(args(season=2025)) == 2
    assert "current season" in capsys.readouterr().out


def test_backfill_refuses_when_it_cannot_identify_the_chat(monkeypatch, capsys) -> None:
    """No production target row and no --chat-name is a refusal, never a guess,
    and the repository never carries the name."""
    monkeypatch.setattr(trades_cli, "load_settings", lambda: settings())
    monkeypatch.setattr(trades_cli, "build_deps", lambda: SimpleNamespace(
        settings=settings(), conn=object(), client=object(), notifier=None))
    monkeypatch.setattr(trades_cli, "current_season", lambda _conn: 2026)
    monkeypatch.setattr(trades_cli, "resolve_chat_guid", lambda _c, _t, _n: None)
    assert trades_cli.cmd_backfill(args(season=2025)) == 2
    out = capsys.readouterr().out
    assert "--chat-name" in out


def test_resolve_chat_guid_prefers_the_production_target_row() -> None:
    target = SimpleNamespace(chat_guid="from-db")
    assert trades_cli.resolve_chat_guid(None, target, "a name") == "from-db"


def test_resolve_chat_guid_falls_back_to_the_display_name() -> None:
    class FakeClient:
        def chat_query(self, limit=1000, offset=0):
            return [{"guid": "from-name", "displayName": "a name"}]

    assert trades_cli.resolve_chat_guid(FakeClient(), None, "a name") == "from-name"
    assert trades_cli.resolve_chat_guid(FakeClient(), None, None) is None
```

```python
# add to packages/league-automation/tests/cli/test_trades.py
def test_trades_help_lists_backfill() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "trades", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0 and "backfill" in result.stdout


def test_backfill_help_lists_its_flags() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "trades", "backfill", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    for flag in ("--season", "--source", "--chat-name", "--dry-run", "--limit"):
        assert flag in result.stdout
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/cli -v`

Expected: FAIL — `cmd_backfill` and `resolve_chat_guid` are not defined.

- [ ] **Step 3: Register the subcommand**

```python
# packages/league-automation/src/ultimate_guillotine/cli/trades.py, inside register()
    backfill = trades_sub.add_parser(
        "backfill",
        help="load one past season of trades from the chat archive and the contracts sheet",
    )
    backfill.add_argument("--season", type=positive_int, required=True)
    backfill.add_argument("--source", choices=("chat", "xlsx", "both"), default="both")
    backfill.add_argument("--xlsx", default=None, help="path to that season's all-contracts.xlsx")
    backfill.add_argument(
        "--chat-name",
        default=None,
        help="the chat's display name, used only when no production delivery target is stored",
    )
    backfill.add_argument(
        "--expected-rosters",
        type=positive_int,
        default=None,
        help="roster count the past league must report (default: the current season's)",
    )
    backfill.add_argument(
        "--dry-run", action="store_true", help="resolve only; write nothing and send nothing"
    )
    backfill.add_argument(
        "--limit", type=positive_int, default=None, help="stop after this many candidate rows"
    )
    backfill.set_defaults(handler=cmd_backfill)
```

- [ ] **Step 4: Implement the command**

```python
def current_season(conn) -> int | None:
    """The newest season on file. A seam so the refusal can be tested."""
    return SeasonRepository(conn).current()


def resolve_chat_guid(client, target, display_name: str | None) -> str | None:
    """The chat to read: the stored production target, else an exact display name.

    Never a hard-coded name and never a fuzzy match. The GUID that comes back is
    passed straight to the archive reader and is never printed or logged.
    """
    if target is not None:
        return target.chat_guid
    if not display_name:
        return None
    return find_chat_guid(client, display_name)


def cmd_backfill(args: argparse.Namespace) -> int:
    """Load one past season of trades. Reads BlueBubbles; never writes to it."""
    # Read off settings before anything connects: a backfill pointed at a
    # production league must not so much as open a connection to it.
    if not args.dry_run and load_settings().delivery_mode is DeliveryMode.PRODUCTION:
        print("backfill refuses to write in production; unset DELIVERY_MODE or use --dry-run")
        return 2

    deps = build_deps()
    conn = deps.conn
    newest = current_season(conn)
    if newest is not None and args.season >= newest:
        print(f"{args.season} is the current season or newer; the backfill only loads history")
        return 2

    season = args.season
    expected = args.expected_rosters or _expected_rosters(conn, newest)
    league_id = find_season_league(
        SleeperClient(httpx.Client()), deps.settings.sleeper_league_id, season, expected
    )
    if not args.dry_run:
        SeasonRepository(conn).upsert(season, league_id, rules_version_for(season), expected)
        report = sync_historical_teams(SleeperClient(httpx.Client()), conn, season, league_id)
        conn.commit()
        print(f"season {season}: {report.members_matched} members matched, "
              f"{report.members_created} created, {report.teams} teams, "
              f"{report.skipped_rosters} rosters skipped")

    rosters = build_roster_index(SleeperClient(httpx.Client()), conn, league_id, season)
    if not rosters.holdings:
        print(f"rosters: no public.teams rows for {season}; "
              "member disambiguation will be weaker on this pass")

    chat_hash = ""
    chat: list = []
    if args.source in ("chat", "both"):
        target = TargetRepository(conn).get(DeliveryMode.PRODUCTION)
        chat_guid = resolve_chat_guid(deps.client, target, args.chat_name)
        if chat_guid is None:
            print("no production delivery target on file; pass --chat-name to name the chat")
            return 2
        chat_hash = chat_guid_hash(chat_guid)
        messages = scan_messages(deps.client, chat_guid, season_window(season))
        chat, scanned = chat_candidates(messages)
        print(f"chat: {scanned} messages scanned, {len(chat)} candidates")
        chat = order_candidates(chat)

    sheet: list = []
    if args.source in ("xlsx", "both"):
        if not args.xlsx:
            print("--source xlsx needs --xlsx <path to all-contracts.xlsx>")
            return 2
        sheet = order_candidates(xlsx_candidates(load_contract_rows(args.xlsx), season))
        print(f"xlsx: {len(sheet)} candidate rows")

    if args.limit is not None:
        chat, sheet = chat[: args.limit], sheet[: args.limit]

    runner = BackfillRunner(
        ai=build_ai(deps), conn=conn, season=season, chat_hash=chat_hash,
        members=MemberAliasRepository(conn).all_members(),
        players=PlayerRepository(conn).all_active(),
        rosters=rosters,
        trades=TradeRepository(conn, "T"),
        runs=RunRepository(conn),
        sources=SourceMessageRepository(conn),
        dry_run=args.dry_run,
    )
    if chat:
        runner.run_pass(chat, pass_number=1, label="chat")
    if sheet:
        runner.run_pass(sheet, pass_number=2, label="xlsx")

    path = review_path(season)
    print(f"review: {write_review(path, runner.reviews)} rows -> {path}")
    for line in dedupe_report_lines(runner.outcomes):
        print(line)
    if not args.dry_run:
        for line in spot_check_lines(TradeRepository(conn, "T"), season):
            print(line)
    return 0
```

Notes for the implementer:

- The trade-code prefix is the literal `"T"`, not `code_prefix_for(deps.settings.delivery_mode)`: history must not be numbered `TEST-` because the machine happens to be in test mode.
- `_expected_rosters(conn, newest)` reads `select expected_rosters from public.seasons where year = %s` for the newest season, defaulting to 18 when there is no season row at all. The spec verifies the discovered league against "that season's `expected_rosters`", but that value lives on the row this check gates, so the current season's value is the default and `--expected-rosters` overrides it.
- `--limit N` caps each pass at N candidates, which is what "a cheap first look" means for `--source both`.
- Add the new imports at the top of `cli/trades.py`: `find_chat_guid`, `scan_messages`, `season_window`, `find_season_league`, `rules_version_for`, `sync_historical_teams`, `chat_candidates`, `xlsx_candidates`, `order_candidates`, `BackfillRunner`, `review_path`, `write_review`, `spot_check_lines`, `dedupe_report_lines`, `chat_guid_hash`, `SourceMessageRepository`.
- `spot_check_lines` and `dedupe_report_lines` arrive in Task 10. Until then, import them from `ultimate_guillotine.history.report` and create that module with the two functions returning `[]`, so this task's tests run; Task 10 fills them in and tests them.
- The model client: pass `build_ai(deps)` today. When `ultimate_guillotine.ai.hermes` lands, switch this one call to `HermesStructuredClient` — nothing else in the backfill knows which client it is.

- [ ] **Step 5: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation
git commit -m "feat: add ug trades backfill"
```

---

### Task 10: Verification output and the operator runbook

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/history/report.py`
- Create: `packages/league-automation/tests/history/test_report.py`
- Modify: `docs/runbooks/mac-mini.md`

**Interfaces:**
- Consumes: `TradeRepository.list_for_season` (Task 4), `RowOutcome`, `Candidate`.
- Produces:
  - `spot_check_lines(trades, season: int, count: int = 10) -> list[str]`
  - `dedupe_report_lines(outcomes: list[tuple[Candidate, RowOutcome]]) -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/history/test_report.py
from datetime import UTC, datetime

from ultimate_guillotine.history.candidates import Candidate
from ultimate_guillotine.history.report import dedupe_report_lines, spot_check_lines
from ultimate_guillotine.history.runner import RowOutcome

WHEN = datetime(2025, 9, 25, tzinfo=UTC)


class FakeTrades:
    def __init__(self, rows) -> None:
        self._rows = rows

    def list_for_season(self, season):
        return self._rows


def trade(code: str) -> dict:
    return {
        "trade_id": 1, "trade_code": code, "status": "accepted", "revision": 1,
        "effective_week": 3,
        "terms": {"parties": [{"display_name": "Member01"}, {"display_name": "Member02"}],
                  "evidence_excerpt": "🚨 Trade Alert 🚨\nsecond line never printed"},
    }


def test_spot_check_walks_the_season_evenly_and_prints_one_line_each() -> None:
    rows = [trade(f"T-2025-{n:03d}") for n in range(1, 21)]
    lines = spot_check_lines(FakeTrades(rows), 2025, count=5)
    assert len(lines) == 6 and lines[0] == "spot check: 5 of 20 accepted trades"
    assert lines[1].startswith("T-2025-001  week 3  Member01, Member02  🚨 Trade Alert 🚨")
    assert "second line" not in "\n".join(lines)
    assert [line.split("  ")[0] for line in lines[1:]] == [
        "T-2025-001", "T-2025-005", "T-2025-009", "T-2025-013", "T-2025-017"
    ]


def test_spot_check_of_a_short_season_lists_everything_it_has() -> None:
    lines = spot_check_lines(FakeTrades([trade("T-2025-001")]), 2025, count=10)
    assert len(lines) == 2


def test_spot_check_of_an_empty_season_says_so() -> None:
    assert spot_check_lines(FakeTrades([]), 2025) == ["spot check: no accepted trades"]


def test_dedupe_report_counts_the_four_populations_and_names_the_disagreements() -> None:
    chat = Candidate("chat", 1, "g1", "t", WHEN, None)
    sheet_same = Candidate("xlsx", 1, "xlsx:2025:row-1", "t", WHEN, 3)
    sheet_differs = Candidate("xlsx", 2, "xlsx:2025:row-2", "t", WHEN, 4)
    sheet_only = Candidate("xlsx", 3, "xlsx:2025:row-3", "t", WHEN, 5)
    outcomes = [
        (chat, RowOutcome("created", trade_code="T-2025-001")),
        (Candidate("chat", 2, "g2", "t", WHEN, None),
         RowOutcome("created", trade_code="T-2025-002")),
        (sheet_same, RowOutcome("duplicate", trade_code="T-2025-001")),
        (sheet_differs, RowOutcome("revised", trade_code="T-2025-002")),
        (sheet_only, RowOutcome("created", trade_code="T-2025-003")),
    ]
    lines = dedupe_report_lines(outcomes)
    assert lines == [
        "dedupe: 2 sheet rows matched a chat trade, 1 sheet-only, 0 chat trades with no sheet row",
        "dedupe: terms disagreed on T-2025-002",
    ]


def test_dedupe_report_is_silent_when_there_were_no_spreadsheet_rows() -> None:
    chat = Candidate("chat", 1, "g1", "t", WHEN, None)
    assert dedupe_report_lines([(chat, RowOutcome("created", trade_code="T-2025-001"))]) == []
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_report.py -v`

Expected: FAIL — both functions return `[]` (the placeholders from Task 9).

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/history/report.py
"""What a backfill tells its operator when the pass is over.

Both reports go to Ben's terminal on the Mac mini and nowhere else -- not to
Supabase, not to Discord, not to a file. The spot check is the only place the
backfill prints anything from an announcement, and it prints one line of one
excerpt for ten trades so a human can recognise deals he was there for.
"""

from ultimate_guillotine.history.candidates import Candidate
from ultimate_guillotine.history.runner import RowOutcome


def spot_check_lines(trades, season: int, count: int = 10) -> list[str]:
    """``count`` evenly spaced accepted trades, for Ben to recognise.

    Evenly spaced rather than the first ten: the first ten are all September,
    and a load that went wrong in November would pass a spot check of its own
    opening weeks.
    """
    rows = trades.list_for_season(season)
    if not rows:
        return ["spot check: no accepted trades"]
    step = max(1, len(rows) // count)
    picked = rows[::step][:count]
    lines = [f"spot check: {len(picked)} of {len(rows)} accepted trades"]
    for row in picked:
        terms = row["terms"] or {}
        parties = ", ".join(p.get("display_name", "?") for p in terms.get("parties", []))
        week = row["effective_week"] if row["effective_week"] is not None else "-"
        first_line = (terms.get("evidence_excerpt") or "").splitlines()[:1]
        lines.append(f"{row['trade_code']}  week {week}  {parties}  {first_line[0] if first_line else ''}")
    return lines


def dedupe_report_lines(outcomes: list[tuple[Candidate, RowOutcome]]) -> list[str]:
    """How the two sources agreed, and where they did not.

    The disagreements are the interesting output: a trade the chat announced one
    way and the ledger records another is either a transcription slip or a
    correction nobody announced, and both are worth a look.
    """
    sheet = [(c, r) for c, r in outcomes if c.source == "xlsx"]
    if not sheet:
        return []
    chat_codes = {r.trade_code for c, r in outcomes if c.source == "chat" and r.trade_code}
    matched = [r for _c, r in sheet if r.outcome in ("duplicate", "revised")]
    sheet_only = [r for _c, r in sheet if r.outcome == "created"]
    disagreed = sorted({r.trade_code for r in matched if r.outcome == "revised" and r.trade_code})
    unmatched_chat = sorted(chat_codes - {r.trade_code for r in matched})
    lines = [
        f"dedupe: {len(matched)} sheet rows matched a chat trade, "
        f"{len(sheet_only)} sheet-only, {len(unmatched_chat)} chat trades with no sheet row"
    ]
    if disagreed:
        lines.append("dedupe: terms disagreed on " + ", ".join(disagreed))
    return lines
```

- [ ] **Step 4: Write the runbook section**

Append to `docs/runbooks/mac-mini.md`, after section 8:

````markdown
## 9. League history backfill

`ug trades backfill` loads one *past* season of trades into Supabase from
two sources: the league chat archive and the contracts spreadsheet. It is a
one-time operator task, run on the Mac mini, and it is strictly read-only
against BlueBubbles — it issues `GET /api/v1/ping`, `POST /api/v1/chat/query`
(a read-only listing), and `GET /api/v1/chat/<guid>/message`, and holds no
reference to the delivery service. The league sees nothing: no send, no read
receipt, no typing indicator, no reaction.

It refuses to write when `DELIVERY_MODE` is `production`, and it refuses any
`--season` at or newer than the newest `public.seasons` row. The current
season's alerts belong to the live Trade Registrar and must stay free to
become that season's first real trade codes.

### Dry run first

```bash
uv run --project packages/league-automation ug trades backfill \
  --season 2025 --source both \
  --xlsx history/contracts/2025-26/all-contracts.xlsx \
  --dry-run --limit 15
```

A dry run resolves and writes nothing — no season row, no team rows, no
trades, no run keys. On the very first dry run there are no `public.teams`
rows for that season yet, so it prints `rosters: no public.teams rows for
2025` and resolves without roster evidence; that is expected. It costs one
model call per candidate row.

### Write mode

Drop `--dry-run`. The pass creates the season row (`rules_version`
`historical-<year>`), that season's members and teams from the verified
`previous_league_id` chain, and then the trades — chat first in message
order, then the spreadsheet as a correcting revision.

```bash
uv run --project packages/league-automation ug trades backfill \
  --season 2025 --source both \
  --xlsx history/contracts/2025-26/all-contracts.xlsx
```

The chat is found from the stored production delivery target. If no
production target has been set yet, pass `--chat-name '<the chat's display
name>'` — the name is typed on the command line and is never stored in this
repository, this runbook, or any log.

### Reading the output

Each row prints `<source> <ordinal>: <outcome>`, where the outcome is one
of `created`, `duplicate`, `revised`, `rescinded`, `clarification: <code>`,
`not-a-trade`, `not-a-candidate`, `failed`, or `skipped`. The clarification
code is one of `ambiguous-member`, `unknown-player`, `unclear`, `invalid` —
the registrar's full sentence is not printed, because it quotes the
announcement.

A summary line closes each pass, then the review file line, then the dedupe
report, then the spot check.

### The review loop

Unresolved rows land in `data/private/backfill/<season>-review.tsv` (that
tree is git-ignored). One line per row: pass, source, ordinal, code, and the
one token that failed to resolve. Nothing else is written down.

1. Read the file. `ambiguous-member` and `unknown-player` rows name a token.
2. Add the token as a nickname in the members JSON and load it:
   `uv run --project packages/league-automation ug members aliases load data/private/league-members.json`
3. Rerun the same command. Rows that already landed are skipped with no
   model call; rows that failed are retried. The review file is rewritten
   from scratch, so it should shrink.
4. Stop when it is empty, or when what is left is rows you choose to leave.

### Verifying a load

1. Row counts by season:
   `select s.year, count(*) from public.trades t join public.seasons s on s.id = t.season_id group by s.year order by s.year`.
   Expect materially fewer trades than the pass reported candidates:
   reposts, amendments, and rescissions collapse.
2. The spot check the pass printed: recognise three of the ten deals. The
   recorded `source_message_guid` on the revision is the tiebreaker if you
   want to find the message.
3. The dedupe report: `terms disagreed on ...` is the interesting line.
4. Boundary check: the current season's trade count is unchanged by every
   backfill run.

### Rollback

Nothing in this repository can undo a backfill — `automation_worker` holds
no `DELETE` grant on `public.trades`, `public.trade_revisions`, or
`public.league_events`, by design. Rollback is by hand in the Supabase
dashboard, one season at a time, in this order:

1. `delete from public.league_events where season_id = <id> and event_type in ('trade', 'trade_rescinded')`
2. `update public.trades set current_revision_id = null where season_id = <id>`
3. `delete from public.trade_revisions where trade_id in (select id from public.trades where season_id = <id>)`
4. `delete from public.trades where season_id = <id>`
5. `delete from private.source_messages where trigger_name = 'trade-alert-backfill'` and
   `delete from private.agent_runs where idempotency_key like 'trade:backfill:<season>:%'`
6. Optionally that season's `public.teams` rows and its `public.seasons` row.

Members created for departed players are left alone; deleting them would
break any other season that referenced them.

### If it stops

- BlueBubbles unreachable or the archive query timing out: the pass stops
  and reports how far it got. Rerun; finished rows are skipped.
- The model unavailable: the row is recorded `failed`, appears in the review
  file, and is retried by the next pass. No Discord alert is sent — a past
  season fails on rows nobody is going to fix.
- A `previous_league_id` walk that cannot be verified: the pass refuses to
  insert a season row and says which check failed. It never guesses a league
  id. Pass `--expected-rosters` if that season genuinely had a different
  roster count.
- Supabase unavailable mid-pass: the transaction rolls back and the row is
  re-reserved as a retry on the next pass. An interrupted backfill leaves a
  consistent prefix; codes already allocated are never renumbered, so a
  resumed run can leave codes slightly out of chronological order. If that
  matters, roll the season back and reload it rather than patching.
````

Do not record any GUID, handle, chat name, or message text in this file.

- [ ] **Step 5: Run the real dry run on the Mac mini**

Run:

```bash
uv run --project packages/league-automation ug trades backfill \
  --season 2025 --source both \
  --xlsx history/contracts/2025-26/all-contracts.xlsx --dry-run --limit 15
```

Record in the report: candidates scanned, rows resolved, rows in the review file by code. Do not paste the review file, the chat name, or any row's token into the report, the commit message, or Discord.

- [ ] **Step 6: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation docs/runbooks/mac-mini.md
git commit -m "feat: report backfill verification and document the operator loop"
```

---

## Spec issues

Contradictions and gaps found while writing this plan, with the resolution each task implements.

1. **`expected_rosters` gates the row it lives on.** The spec verifies a discovered league's `total_rosters` against "that season's `expected_rosters`", but that column is on the `public.seasons` row the verification exists to gate. *Resolution (Tasks 2, 9):* the check compares against the current season's `expected_rosters` by default, and `--expected-rosters N` overrides it; the new season row is inserted with the value that was checked.

2. **`clarification` is not a run status.** The spec says a row that finished `clarification` is re-reserved, but `private.agent_runs.status` is constrained to `running`, `succeeded`, `failed`, `duplicate`. *Resolution (Tasks 7, 8):* an unresolved row finishes `failed` with its review code in `error`, and the rule becomes "anything that is not `succeeded` or `duplicate` re-reserves with a per-attempt suffix", which also covers a run abandoned in `running`.

3. **A season-wide revise window would collapse distinct deals.** The spec widens `REVISE_WINDOW_HOURS` to the season's span because both readings are written seconds apart under back-dated clocks. But `find_by_context` matches on season, parties, and players, so a season-wide window would fold a week 12 deal between the same two members over the same player into the week 3 one. *Resolution (Tasks 4, 8):* add `public.trade_revisions.occurred_at`, anchor the window on the message time instead of the insert time, keep the 72-hour window for the chat pass, and widen it only for the spreadsheet pass, which is the case the spec was actually describing.

4. **The spreadsheet-parties fallback is circular.** Fallback 2 disambiguates a member using the sheet row matched "by the context key below" — but the context key is built from the member ids that the fallback exists to produce. *Resolution (Task 8):* fallback 2 is dropped. An ambiguous member goes straight to the review file as `ambiguous-member` with its token, which is the spec's own fallback 3 and the alias-editing loop the spec describes as the point of the review file.

5. **A dry run cannot both write nothing and resolve everything.** Resolution needs a `RosterIndex`, which needs `public.teams` rows for the past season, which only a write pass creates. *Resolution (Task 9):* the dry run writes nothing at all and resolves with an empty index, printing one line saying roster evidence is unavailable; the first write pass creates the season and team rows, so every later dry run has them.

6. **The review file's contents.** The spec puts "the offending token, and the candidate display names" in the review file. *Resolution (Task 5):* the file carries pass, source, ordinal, code, and the token only. The token is what an alias is written against, so it has to be there; the candidate display names are one `ug members list` away and are not copied into a file. `unclear` and `invalid` rows carry no token at all, because their reason is model prose about the message.

7. **The season's first and last day are undefined.** The spec says the archive is read "up to 23:59:59 America/Chicago on the last day of the requested season" without saying when a season starts or ends. *Resolution (Task 1):* `season_window(year)` is 1 August of the season year to 1 March of the next, in America/Chicago, half-open. It is wide enough for preseason and February trades and closes months before the following season's first alert, which is what makes swallowing a current-season announcement impossible rather than merely unlikely.

8. **Rescissions are not in the pipeline the spec lists.** The spec's Extraction Pipeline has four steps ending in `accept`, but its Verification section expects rescissions to collapse. Accepting a rescission alert as a trade would invent a deal. *Resolution (Task 8):* a proposal whose kind is `rescission` rescinds the trade its context key names, searched across the season span; an unmatched one is a review row with code `unclear`.

9. **Stubbed delivery and notifier.** The spec asks for a `_SilentDelivery`-style stub and a stubbed notifier. *Resolution (Task 8):* the backfill constructs no `TradeRegistrar`, and therefore no delivery service and no notifier at all — strictly stronger than a stub, since there is no object to mis-wire. `tests/history/test_read_only.py` asserts that no module in the `history` package so much as names `DeliveryService`, `send_text`, `/api/v1/message`, or `ensure_webhook`.

10. **`POST /api/v1/chat/query` is not in the spec's list of calls.** The Privacy section says "Every BlueBubbles call is a `GET`: `/api/v1/ping` and `/api/v1/chat/<guid>/message`", but the scan the spec specifies elsewhere needs the chat query to turn a display name into a GUID. *Resolution (Tasks 1, 9):* the POST stays, documented as the single non-GET call and used only to read the chat list; it is skipped entirely when a production delivery target row supplies the GUID. The read-only tests allow exactly those three paths and assert the send route is never called.

---

## Self-Review Notes

- **Spec coverage.** Inputs: xlsx (Task 6), chat archive (Task 1). Seasons: chain walk and season row (Task 2). Members and teams: Task 3, including departed members and the `sleeper_user_id` match. Extraction pipeline: Task 8 reuses `is_trade_candidate`, `dry_run_pipeline` (one model call), `resolve_extracted` against a historical `RosterIndex` (Tasks 3, 9), `validate`, and `accept`. Weaker roster evidence and the fallback order: Tasks 5 and 8, with fallback 2 dropped per spec issue 4. Dedupe: Tasks 4 and 8 (fingerprint duplicates, context-key revisions, chat authoritative for chain and timing, `"source": "contracts-xlsx"` and a non-GUID `source_message_guid` for ledger rows). Codes, events, evidence: Tasks 4 and 8 (`T` prefix forced, chronological ordering, dated events, `private.source_messages` with a null `sender_hash` and `trigger_name` `trade-alert-backfill`). What is not copied: Global Constraints, enforced by Tasks 5 and 8. Operator workflow, review file, alias loop, `--limit`: Tasks 5, 9, 10. Idempotency: Tasks 4 and 7. Current-season boundary: Tasks 1 and 9. Read-only guarantee: Tasks 1 and 8. Verification: Task 10. Rollback and failure behavior: Task 10's runbook. The spec's seven open questions for Ben are not decided here; the command takes one `--season` at a time and `--source` chooses the sources, so questions 1 and the xlsx-only handling in 4 are runtime choices, and 2, 3, 5, 6 and 7 are implemented as the spec proposes.
- **Placeholder scan.** No step says "add error handling", "similar to Task N", or "write tests for the above"; every code step carries the code, and every test step carries the test. The one deliberate stub is `history/report.py`'s two functions returning `[]` in Task 9, filled in and tested in Task 10, which is called out in both places.
- **Type consistency.** Names used across tasks: `chat_query`, `messages_page`, `season_window`, `find_chat_guid`, `scan_messages`, `previous_league_id`, `find_season_league`, `rules_version_for`, `SeasonRepository.upsert`, `sync_historical_teams`, `TeamSyncReport`, `TradeProposal.source`, `TradeRepository.accept(occurred_at, revise_within_hours)`, `TradeRepository.list_for_season`, `Unresolved.code`/`.token`, `REVIEW_CODES`, `ReviewRow`, `review_row`, `review_path`, `write_review`, `ContractRow`, `load_contract_rows`, `Candidate`, `chat_candidates`, `xlsx_candidates`, `sheet_row_time`, `week_number`, `order_candidates`, `RunRepository.status_for`, `backfill_key`, `reserve_row`, `BACKFILL_AGENT`, `NOT_A_TRADE`, `dry_run_pipeline`, `summary_line`, `RowOutcome`, `BackfillRunner.run_row`/`.run_pass`, `SEASON_SPAN_HOURS`, `spot_check_lines`, `dedupe_report_lines`, `resolve_chat_guid`, `current_season`, `cmd_backfill`.
- **Decisions recorded for the controller.** Trade codes are `T-` even in test mode. The dry run never writes, at the cost of roster evidence on a first pass. `data/private/backfill/` is covered by the existing `data/private/*` ignore rule, so no `.gitignore` change is made. `sync_season` is left alone; history gets its own team sync rather than loosening the live one.
