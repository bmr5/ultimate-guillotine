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
    "week": 1,
    "leg": 1,
    "season_type": "regular",
    "season": "2026",
    "league_season": "2026",
    "previous_season": "2025",
    "season_start_date": "2026-09-09",
    "display_week": 1,
    "league_create_season": "2026",
    "season_has_scores": True,
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
