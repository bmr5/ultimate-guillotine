"""What one run leaves behind: a survival snapshot, a recap row, and the run's version.

Against the local database, because the whole value of each write is its
conflict target: the snapshot's natural key makes a replay a no-op, and the recap
row is what stops a second post the same night.
"""

from datetime import UTC, datetime

from tests.summary.helpers import done_team, snapshot
from ultimate_guillotine.data.repositories import RunRepository
from ultimate_guillotine.summary.store import SummaryRepository, results_payload
from ultimate_guillotine.summary.survival import simulate

NOW = datetime(2026, 9, 14, 4, 50, tzinfo=UTC)
WINDOW = "eod:2026-09-13"
KIND = "eod:2026-09-13"


def _season_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        return cur.fetchone()[0]


def _result():
    return simulate(snapshot((done_team(1, "100"), done_team(2, "90"), done_team(3, "80"))),
                    simulations=20)


def test_results_payload_carries_each_team_s_label_and_numbers_as_json_numbers() -> None:
    snap = snapshot((done_team(1, "100"), done_team(2, "90"), done_team(3, "80")))
    payload = results_payload(snap, simulate(snap, simulations=20))
    assert [row["team_id"] for row in payload] == [1, 2, 3]
    assert payload[2] == {
        "team_id": 3,
        "label": "Member03",
        "points": 80.0,
        "projected_final": 80.0,
        "pending": 0,
        "adverse_event": "gulag_entry",
        "probability": 1.0,
        "is_estimated": False,
    }


def test_the_same_snapshot_is_recorded_once(conn) -> None:
    repo = SummaryRepository(conn)
    season_id = _season_id(conn)
    snap = snapshot((done_team(1, "100"), done_team(2, "90"), done_team(3, "80")))
    result = simulate(snap, simulations=20)
    assert repo.record_snapshot(season_id, 1, WINDOW, snap, result, NOW) is True
    assert repo.record_snapshot(season_id, 1, WINDOW, snap, result, NOW) is False
    with conn.cursor() as cur:
        cur.execute(
            "select simulations, model_version, projection_source, jsonb_array_length(results)"
            " from public.survival_snapshots where season_id = %s and game_window = %s",
            (season_id, WINDOW),
        )
        assert cur.fetchall() == [(20, result.model_version, "sleeper", 3)]


def test_a_recap_starts_as_a_draft_and_is_sent_once_marked(conn) -> None:
    repo = SummaryRepository(conn)
    season_id = _season_id(conn)
    assert repo.sent_today(season_id, 1, KIND) is False
    recap_id = repo.record_recap(season_id, 1, KIND, "2026.1", "abc", "the body")
    assert repo.sent_today(season_id, 1, KIND) is False
    repo.mark_sent(recap_id)
    assert repo.sent_today(season_id, 1, KIND) is True
    with conn.cursor() as cur:
        cur.execute("select body, publication_state from public.recaps where id = %s", (recap_id,))
        assert cur.fetchone() == ("the body", "sent")


def test_recording_the_same_recap_twice_returns_the_same_row(conn) -> None:
    repo = SummaryRepository(conn)
    season_id = _season_id(conn)
    first = repo.record_recap(season_id, 1, KIND, "2026.1", "abc", "the body")
    second = repo.record_recap(season_id, 1, KIND, "2026.1", "abc", "the body")
    assert first == second


def test_the_run_s_input_version_is_written_where_the_audit_reads_it(conn) -> None:
    runs = RunRepository(conn)
    run_id = runs.reserve("eod-summary", "cli", "eod-test:1")
    SummaryRepository(conn).set_input_version(run_id, "mc-2026.1:2026.1:some-model")
    with conn.cursor() as cur:
        cur.execute("select input_version from private.agent_runs where id = %s", (run_id,))
        assert cur.fetchone() == ("mc-2026.1:2026.1:some-model",)
