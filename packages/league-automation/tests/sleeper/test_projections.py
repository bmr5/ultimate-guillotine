import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ultimate_guillotine.sleeper.projections import (
    ProjectionRepository,
    load_projections,
    projection_week,
    sync_current_week_projections,
    sync_projections,
)
from ultimate_guillotine.sleeper.scoring import scoring_version
from ultimate_guillotine.sleeper.state import parse_nfl_state

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "projections_2026_w1.json"
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=6)
SETTINGS = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "sleeper" / "league_2026.json").read_text()
)["scoring_settings"]

# Recorded NFL state: regular season week 1, plus the preseason shape that must never be
# projected -- `week` restarts inside the season type, so a preseason 3 is not week 3.
STATE_RAW = {
    "week": 1,
    "leg": 1,
    "season_type": "regular",
    "season": "2026",
    "previous_season": "2025",
    "season_start_date": "2026-09-09",
    "display_week": 1,
}
PRE_STATE_RAW = {**STATE_RAW, "week": 3, "season_type": "pre", "display_week": 1}


def payload() -> list[dict]:
    return json.loads(FIXTURE.read_text())


class FakeProjClient:
    def __init__(self, rows: list[dict], state: dict | None = None) -> None:
        self.rows = rows
        self.calls = 0
        self.state = STATE_RAW if state is None else state

    def get_projections(self, season: int, week: int) -> list[dict]:
        self.calls += 1
        return self.rows

    def get_nfl_state(self) -> dict:
        return self.state


class OutageClient:
    """Sleeper is down: the fetch raises instead of answering."""

    def __init__(self) -> None:
        self.calls = 0

    def get_projections(self, season: int, week: int) -> list[dict]:
        self.calls += 1
        raise ConnectionError("sleeper is unreachable")


class Boom(Exception):
    """The caller's own failure, raised after the write inside the caller's transaction."""


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


def test_the_stat_line_round_trips_as_a_queryable_json_object(conn) -> None:
    """One jsonb object, not a double-encoded string: the rescore path scores these keys."""
    sync_projections(FakeProjClient(bulk(payload(), 250)), conn, 2026, 1, SETTINGS, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select stat_line, stat_line->>'rec_yd' from public.player_projections "
            "where season = 2026 and week = 1 and sleeper_player_id = '9488'"
        )
        stat_line, rec_yd = cur.fetchone()
    assert isinstance(stat_line, dict)
    assert stat_line["rec"] == 6.83 and float(rec_yd) == 94.17


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


def test_rescore_leaves_synced_at_alone(conn) -> None:
    """A rescore refetches nothing, so it must not claim the row was synced again."""
    client = FakeProjClient(bulk(payload(), 250))
    sync_projections(client, conn, 2026, 1, SETTINGS, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, synced_at from public.player_projections "
            "where season = 2026 and week = 1 order by sleeper_player_id"
        )
        before = cur.fetchall()
    sync_projections(client, conn, 2026, 1, {**SETTINGS, "rec": 2.0}, LATER, rescore=True)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, synced_at from public.player_projections "
            "where season = 2026 and week = 1 order by sleeper_player_id"
        )
        assert cur.fetchall() == before
    assert {stamp for _pid, stamp in before} == {NOW}


def test_rescore_refuses_a_week_with_nothing_stored(conn) -> None:
    with pytest.raises(RuntimeError, match="no stored projections for 2026 week 4"):
        sync_projections(FakeProjClient([]), conn, 2026, 4, SETTINGS, NOW, rescore=True)


def test_a_player_who_leaves_the_feed_keeps_his_row_and_loses_his_points(conn) -> None:
    """Missing is not zero and not gone: null the points, keep the row and its stamp."""
    sync_projections(FakeProjClient(bulk(payload(), 250)), conn, 2026, 1, SETTINGS, NOW)
    without_9488 = [r for r in payload() if r["player_id"] != "9488"]
    sync_projections(FakeProjClient(bulk(without_9488, 250)), conn, 2026, 1, SETTINGS, LATER)
    with conn.cursor() as cur:
        cur.execute(
            "select league_points, synced_at, stat_line->>'rec' "
            "from public.player_projections "
            "where season = 2026 and week = 1 and sleeper_player_id = '9488'"
        )
        points, synced_at, rec = cur.fetchone()
        cur.execute(
            "select league_points, synced_at from public.player_projections "
            "where season = 2026 and week = 1 and sleeper_player_id = '12517'"
        )
        kept_points, kept_synced_at = cur.fetchone()
        cur.execute("select count(*) from public.player_projections where week = 1")
        total = cur.fetchone()[0]
    # The row survives, with its stat line and the stamp of the run that last carried it.
    assert points is None and synced_at == NOW and float(rec) == 6.83
    # A player still in the feed is rescored and restamped as usual, and nothing is deleted.
    assert kept_points is not None and kept_synced_at == LATER
    assert total == 257


def test_a_fetch_outage_leaves_the_prior_runs_rows_untouched(conn) -> None:
    sync_projections(FakeProjClient(bulk(payload(), 250)), conn, 2026, 1, SETTINGS, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, synced_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        before = cur.fetchall()
    client = OutageClient()
    with pytest.raises(ConnectionError):
        sync_projections(client, conn, 2026, 1, SETTINGS, LATER)
    assert client.calls == 1
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, synced_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        assert cur.fetchall() == before
    assert {stamp for *_rest, stamp in before} == {NOW}


def test_flag_coverage_marks_the_runs_rows(conn) -> None:
    sync_projections(FakeProjClient(bulk(payload(), 250)), conn, 2026, 1, SETTINGS, NOW)
    ProjectionRepository(conn).flag_coverage(2026, 1, Decimal("81.25"), flagged=True)
    with conn.cursor() as cur:
        cur.execute(
            "select distinct coverage_flagged, run_coverage_pct "
            "from public.player_projections where week = 1"
        )
        assert cur.fetchall() == [(True, Decimal("81.25"))]


def test_the_write_runs_inside_the_callers_transaction(conn) -> None:
    """Task 10 wraps this write and the team-week recompute in one transaction, so the
    write must join the caller's transaction and be discarded with it."""
    client = FakeProjClient(bulk(payload(), 250))
    with pytest.raises(Boom), conn.transaction():
        sync_projections(client, conn, 2026, 1, SETTINGS, NOW)
        raise Boom
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.player_projections where week = 1")
        assert cur.fetchone()[0] == 0


def test_projection_week_reads_the_regular_season_week_from_state() -> None:
    assert projection_week(parse_nfl_state(STATE_RAW, NOW)) == (2026, 1)


def test_projection_week_refuses_a_preseason_week() -> None:
    with pytest.raises(RuntimeError, match="regular season"):
        projection_week(parse_nfl_state(PRE_STATE_RAW, NOW))


def test_the_current_week_sync_never_fetches_a_preseason_slate(conn) -> None:
    client = FakeProjClient(bulk(payload(), 250), state=PRE_STATE_RAW)
    with pytest.raises(RuntimeError, match="regular season"):
        sync_current_week_projections(client, conn, SETTINGS, NOW)
    assert client.calls == 0
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.player_projections")
        assert cur.fetchone()[0] == 0


def test_the_current_week_sync_writes_the_week_state_reports(conn) -> None:
    client = FakeProjClient(bulk(payload(), 250))
    report = sync_current_week_projections(client, conn, SETTINGS, NOW)
    assert report.rows == 257
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.player_projections where season = 2026 and week = 1"
        )
        assert cur.fetchone()[0] == 257
