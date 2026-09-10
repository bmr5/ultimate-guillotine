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
    broken = _pick(1, 1, "p1", "53")
    broken["player_id"] = None
    payload = [broken] + PAYLOAD[1:]
    with pytest.raises(ValueError, match="pick 1 is malformed"):
        load_draft_picks(DRAFT, payload, TEAMS)


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
    assert rows[0][8] == datetime(2026, 9, 7, 23, 1, 30, 433000, tzinfo=UTC)


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
    with pytest.raises(ValueError, match=r"roster \d+ has no team row"):
        sync_draft(FakeClient(), conn, LEAGUE_ID, season_id, NOW)
    assert _rows(conn) == []
