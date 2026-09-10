"""The projections fetch and the repository writes `ug sleeper projections` composes.

There is no `sync_projections` wrapper any more: the CLI owns the composition, so
these tests call the two halves the way it does -- `fetch_projection_rows` outside
the transaction, then `ProjectionRepository.upsert_many` or `.rescore` -- and pin
what each half does against a real database.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ultimate_guillotine.sleeper.projections import (
    ProjectionRepository,
    WeekFlags,
    fetch_projection_rows,
    load_projections,
)
from ultimate_guillotine.sleeper.scoring import scoring_version

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "projections_2026_w1.json"
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=6)
SETTINGS = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "sleeper" / "league_2026.json").read_text()
)["scoring_settings"]
VERSION = scoring_version(SETTINGS)


def payload() -> list[dict]:
    return json.loads(FIXTURE.read_text())


class FakeProjClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls = 0

    def get_projections(self, season: int, week: int) -> list[dict]:
        self.calls += 1
        return self.rows


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


def sync(conn, client, season=2026, week=1, settings=None, now=NOW):
    """Fetch then upsert, in the order and with the calls `cmd_projections` uses."""
    settings = SETTINGS if settings is None else settings
    rows = fetch_projection_rows(client, season, week, now)
    return ProjectionRepository(conn).upsert_many(
        season, week, rows, settings, scoring_version(settings), now
    )


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
    report = sync(conn, FakeProjClient(bulk(payload(), 250)))
    assert report.rows == 257 and report.scoring_version == VERSION
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
    assert version == VERSION and projected_at is not None


def test_the_stat_line_round_trips_as_a_queryable_json_object(conn) -> None:
    """One jsonb object, not a double-encoded string: the rescore path scores these keys."""
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    with conn.cursor() as cur:
        cur.execute(
            "select stat_line, stat_line->>'rec_yd' from public.player_projections "
            "where season = 2026 and week = 1 and sleeper_player_id = '9488'"
        )
        stat_line, rec_yd = cur.fetchone()
    assert isinstance(stat_line, dict)
    assert stat_line["rec"] == 6.83 and float(rec_yd) == 94.17


def test_a_stat_line_the_league_cannot_score_stays_null_not_zero(conn) -> None:
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    with conn.cursor() as cur:
        cur.execute(
            "select league_points from public.player_projections "
            "where season = 2026 and week = 1 and sleeper_player_id = '10881'"
        )
        assert cur.fetchone()[0] is None


def test_a_thin_payload_is_refused_before_anything_is_written(conn) -> None:
    """The refusal is in the fetch, which the command runs before it opens its
    transaction, so a broken payload cannot reach a write at all."""
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    with pytest.raises(RuntimeError, match="too few"):
        fetch_projection_rows(FakeProjClient(payload()), 2026, 1, NOW)
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.player_projections where week = 1")
        assert cur.fetchone()[0] == 257


def test_an_empty_payload_is_refused(conn) -> None:
    with pytest.raises(RuntimeError, match="too few"):
        fetch_projection_rows(FakeProjClient([]), 2026, 1, NOW)


def test_repeated_runs_produce_identical_rows(conn) -> None:
    client = FakeProjClient(bulk(payload(), 250))
    sync(conn, client)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, projected_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        first = cur.fetchall()
    sync(conn, client)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, projected_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        assert cur.fetchall() == first


def test_rescore_recomputes_from_stored_stat_lines_without_refetching(conn) -> None:
    client = FakeProjClient(bulk(payload(), 250))
    sync(conn, client)
    client.calls = 0
    doubled = {**SETTINGS, "rec": 2.0}
    report = ProjectionRepository(conn).rescore(2026, 1, doubled, scoring_version(doubled), NOW)
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
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, synced_at from public.player_projections "
            "where season = 2026 and week = 1 order by sleeper_player_id"
        )
        before = cur.fetchall()
    doubled = {**SETTINGS, "rec": 2.0}
    ProjectionRepository(conn).rescore(2026, 1, doubled, scoring_version(doubled), LATER)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, synced_at from public.player_projections "
            "where season = 2026 and week = 1 order by sleeper_player_id"
        )
        assert cur.fetchall() == before
    assert {stamp for _pid, stamp in before} == {NOW}


def test_rescore_refuses_a_week_with_nothing_stored(conn) -> None:
    with pytest.raises(RuntimeError, match="no stored projections for 2026 week 4"):
        ProjectionRepository(conn).rescore(2026, 4, SETTINGS, VERSION, NOW)


def test_a_player_who_leaves_the_feed_keeps_his_row_and_loses_his_points(conn) -> None:
    """Missing is not zero and not gone: null the points, keep the row and its stamp."""
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    without_9488 = [r for r in payload() if r["player_id"] != "9488"]
    sync(conn, FakeProjClient(bulk(without_9488, 250)), now=LATER)
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
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, synced_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        before = cur.fetchall()
    client = OutageClient()
    with pytest.raises(ConnectionError):
        sync(conn, client, now=LATER)
    assert client.calls == 1
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, league_points, scoring_version, synced_at "
            "from public.player_projections where week = 1 order by sleeper_player_id"
        )
        assert cur.fetchall() == before
    assert {stamp for *_rest, stamp in before} == {NOW}


def test_flag_coverage_marks_the_runs_rows(conn) -> None:
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    ProjectionRepository(conn).flag_coverage(2026, 1, Decimal("81.25"), flagged=True)
    with conn.cursor() as cur:
        cur.execute(
            "select distinct coverage_flagged, run_coverage_pct "
            "from public.player_projections where week = 1"
        )
        assert cur.fetchall() == [(True, Decimal("81.25"))]


def test_flag_coverage_rewrites_nothing_when_the_stamp_has_not_moved(conn) -> None:
    """The job fires every five minutes through a game window and the stamp is
    usually the one it wrote last time. Rewriting ~9,400 unchanged rows a run is
    dead tuples for the vacuum and a replication stream saying nothing."""
    repo = ProjectionRepository(conn)
    sync(conn, FakeProjClient(bulk(payload(), 250)))

    first = repo.flag_coverage(2026, 1, Decimal("81.25"), flagged=True)
    assert first > 0

    assert repo.flag_coverage(2026, 1, Decimal("81.25"), flagged=True) == 0

    # A stamp that actually moves still lands on every row.
    assert repo.flag_coverage(2026, 1, Decimal("99.00"), flagged=False) == first
    with conn.cursor() as cur:
        cur.execute(
            "select distinct coverage_flagged, run_coverage_pct "
            "from public.player_projections where week = 1"
        )
        assert cur.fetchall() == [(False, Decimal("99.00"))]


def test_week_flags_reads_a_week_with_nothing_stored_as_clear(conn) -> None:
    """The first run of a week has nothing to compare against, so it starts clear
    and a flagged first run reads as a transition worth one note."""
    assert ProjectionRepository(conn).week_flags(2026, 4) == WeekFlags(False, False)


def test_week_flags_reports_the_stored_coverage_stamp(conn) -> None:
    repo = ProjectionRepository(conn)
    sync(conn, FakeProjClient(bulk(payload(), 250)))
    assert repo.week_flags(2026, 1).coverage_flagged is False
    repo.flag_coverage(2026, 1, Decimal("81.25"), flagged=True)
    assert repo.week_flags(2026, 1).coverage_flagged is True
    repo.flag_coverage(2026, 1, Decimal("99.00"), flagged=False)
    assert repo.week_flags(2026, 1).coverage_flagged is False


def test_week_flags_recovers_the_last_runs_drift_verdict_from_the_rows(conn) -> None:
    """Drift is not stored anywhere. It does not have to be: the stored points and
    stat lines are exactly what the last run scored, so re-running the rule over
    them returns that run's verdict."""
    repo = ProjectionRepository(conn)
    clean = sync(conn, FakeProjClient(bulk(payload(), 250)))
    assert clean.drift_flagged is False
    assert repo.week_flags(2026, 1).drift_flagged is False

    # Five points a passing yard: nearly every scored player now sits hundreds of
    # points from every Sleeper preset, which is the shape a broken settings map has.
    wrong = {**SETTINGS, "pass_yd": 5.0}
    drifted = repo.rescore(2026, 1, wrong, scoring_version(wrong), NOW)
    assert drifted.drift_flagged is True
    assert repo.week_flags(2026, 1).drift_flagged is True


def test_the_write_runs_inside_the_callers_transaction(conn) -> None:
    """The command wraps this write and the team-week recompute in one transaction,
    so the write must join the caller's and be discarded with it."""
    client = FakeProjClient(bulk(payload(), 250))
    with pytest.raises(Boom), conn.transaction():
        sync(conn, client)
        raise Boom
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.player_projections where week = 1")
        assert cur.fetchone()[0] == 0
