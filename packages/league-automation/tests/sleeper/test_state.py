from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from ultimate_guillotine.sleeper.state import (
    STATE_MAX_AGE,
    NflStateRepository,
    current_week,
    parse_nfl_state,
    sync_nfl_state,
)

# Recorded from GET https://api.sleeper.app/v1/state/nfl on 2026-09-09, with one
# deliberate change: `leg` is 3 rather than the 1 Sleeper sent. `week`, `display_week`
# and `leg` are adjacent int columns written and read positionally, so equal values
# would let a swapped column survive the round trip unnoticed.
RAW = {
    "week": 1,
    "leg": 3,
    "season_type": "regular",
    "season": "2026",
    "league_season": "2026",
    "previous_season": "2025",
    "season_start_date": "2026-09-09",
    "display_week": 1,
    "league_create_season": "2026",
    "season_has_scores": True,
}
# Preseason: Sleeper restarts `week` inside the season type, while `display_week`
# points at the regular-season week about to start.
PRE_RAW = {
    "week": 3,
    "leg": 3,
    "season_type": "pre",
    "season": "2026",
    "previous_season": "2025",
    "season_start_date": "2026-09-09",
    "display_week": 1,
    "season_has_scores": False,
}
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
# What a caller reaching for `datetime.now()` instead of `datetime.now(UTC)` hands in.
NAIVE_NOW = NOW.replace(tzinfo=None)


class FakeStateClient:
    def __init__(self, raw: dict, week: int | None = None) -> None:
        self.raw = {**raw, **({"week": week} if week is not None else {})}
        self.calls = 0

    def get_nfl_state(self) -> dict:
        self.calls += 1
        return self.raw


class OutageStateClient:
    """Sleeper unreachable: the transport error every httpx failure derives from."""

    def __init__(self) -> None:
        self.calls = 0

    def get_nfl_state(self) -> dict:
        self.calls += 1
        raise httpx.HTTPError("sleeper is unreachable")


def test_parse_coerces_sleepers_string_season_and_date() -> None:
    state = parse_nfl_state(RAW, NOW)
    assert state.season == 2026 and state.previous_season == 2025
    assert state.week == 1 and state.display_week == 1 and state.leg == 3
    assert state.season_type == "regular"
    assert state.season_start_date == date(2026, 9, 9)
    assert state.raw["league_season"] == "2026"
    assert state.synced_at == NOW


def test_parse_rejects_a_payload_without_a_week() -> None:
    with pytest.raises(ValueError, match="week"):
        parse_nfl_state({"season": "2026", "season_type": "regular"}, NOW)


def test_parse_keeps_a_preseason_week_separate_from_display_week() -> None:
    """`week` counts inside `season_type`; preseason week 3 is not regular-season week 3."""
    state = parse_nfl_state(PRE_RAW, NOW)
    assert state.season_type == "pre"
    assert state.week == 3
    assert state.display_week == 1
    assert state.week != state.display_week


def test_parse_rejects_a_naive_now() -> None:
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        parse_nfl_state(RAW, NAIVE_NOW)


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


def test_current_week_treats_exactly_sixty_minutes_as_fresh(conn) -> None:
    """The freshness bound is inclusive: at STATE_MAX_AGE exactly, no Sleeper call."""
    client = FakeStateClient(RAW)
    sync_nfl_state(client, conn, NOW)
    client.calls = 0
    state = current_week(client, conn, NOW + STATE_MAX_AGE)
    assert state.week == 1
    assert client.calls == 0


def test_current_week_raises_on_an_outage_and_leaves_the_stale_row(conn) -> None:
    """A stale week must never be used silently: the outage propagates, the row survives."""
    sync_nfl_state(FakeStateClient(RAW), conn, NOW)
    client = OutageStateClient()

    with pytest.raises(httpx.HTTPError):
        current_week(client, conn, NOW + timedelta(minutes=61))

    assert client.calls == 1
    stored = NflStateRepository(conn).get()
    assert stored is not None
    assert stored.week == 1
    assert stored.synced_at == NOW


def test_current_week_rejects_a_naive_now(conn) -> None:
    client = FakeStateClient(RAW)
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        current_week(client, conn, NAIVE_NOW)
    assert client.calls == 0
