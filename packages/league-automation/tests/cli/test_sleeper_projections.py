"""What `ug sleeper projections` does before, inside, and after its one transaction.

The command is the composition root for Tasks 8 and 9: it fetches outside the
transaction so a thin payload cannot roll anything back, then writes the player
rows, the team-week rows, and the coverage stamp together. These tests fake the
whole world below it -- the point under test is the ordering and the notes, not
the SQL, which Tasks 8 and 9 cover against a real database.
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Self

import pytest

from ultimate_guillotine.cli import sleeper as sleeper_cli
from ultimate_guillotine.sleeper.projections import WeekFlags
from ultimate_guillotine.sleeper.scoring import DRIFT_POINTS

SETTINGS = {"rec": 1.0}
CLEAR = WeekFlags(coverage_flagged=False, drift_flagged=False)


def test_sleeper_help_lists_every_subcommand() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "sleeper", "--help"],
        capture_output=True,
        text=True,
        check=False,
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
        check=False,
    )
    assert result.returncode == 0
    assert "--week" in result.stdout and "--rescore" in result.stdout


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self._conn = conn

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.queries.append((sql, params))

    def fetchone(self) -> tuple | None:
        return self._conn.season_row


class FakeConn:
    """Records the season lookup and every transaction boundary the command opens."""

    def __init__(self, season_row: tuple | None = (4, SETTINGS)) -> None:
        self.season_row = season_row
        self.queries: list[tuple[str, tuple]] = []
        self.events: list[str] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def transaction(self) -> "FakeTransaction":
        return FakeTransaction(self)


class FakeTransaction:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def __enter__(self) -> Self:
        self._conn.events.append("begin")
        return self

    def __exit__(self, exc_type: type[BaseException] | None, *rest: object) -> bool:
        self._conn.events.append("commit" if exc_type is None else "rollback")
        return False


class FakeNotifier:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def ops(self, text: str) -> bool:
        self.notes.append(text)
        return True


@dataclass
class FakeRepo:
    """Stands in for `ProjectionRepository`, recording the writes inside the transaction."""

    conn: FakeConn
    before: WeekFlags = field(default=CLEAR)

    def week_flags(self, season, week):
        # Deliberately not an event: this read happens before the transaction opens,
        # and the ordering assertions below would not catch it if it slipped inside.
        return self.before

    def upsert_many(self, season, week, rows, scoring_settings, version, now):
        self.conn.events.append(f"upsert {season}w{week} {len(rows)} rows")
        return REPORT

    def rescore(self, season, week, scoring_settings, version, now):
        self.conn.events.append(f"rescore {season}w{week}")
        return REPORT

    def flag_coverage(self, season, week, run_coverage_pct, flagged):
        self.conn.events.append(f"flag {run_coverage_pct} flagged={flagged}")


REPORT = SimpleNamespace(
    rows=9400, scored=9400, unscored=0, scoring_version="v1",
    drift_share=Decimal("0.0000"), drift_flagged=False,
)


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: FakeConn,
    season_type: str = "regular",
    season: int = 2026,
    week: int = 3,
    run_pct: Decimal = Decimal("100.00"),
    report: SimpleNamespace = REPORT,
    before: WeekFlags = CLEAR,
    fetch=None,
) -> FakeNotifier:
    notifier = FakeNotifier()
    monkeypatch.setattr(
        sleeper_cli, "build_deps", lambda: SimpleNamespace(conn=conn, notifier=notifier)
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
    monkeypatch.setattr(sleeper_cli, "scoring_version", lambda settings: "v1")
    monkeypatch.setattr(
        sleeper_cli,
        "fetch_projection_rows",
        fetch or (lambda client, s, w, now: [object()] * 9400),
    )

    def fake_repo(target: FakeConn) -> FakeRepo:
        return FakeRepo(target, before)

    monkeypatch.setattr(sleeper_cli, "ProjectionRepository", fake_repo)

    def fake_recompute(target, season_id, season_year, w, now):
        target.events.append("recompute")
        return [SimpleNamespace(is_provisional=run_pct < 95)] * 18, run_pct

    monkeypatch.setattr(sleeper_cli, "recompute_team_week", fake_recompute)
    monkeypatch.setattr(REPORT, "drift_flagged", report.drift_flagged)
    monkeypatch.setattr(REPORT, "drift_share", report.drift_share)
    monkeypatch.setattr(
        sleeper_cli,
        "run_scheduled_with_notes",
        lambda deps, agent, now, action: action(1),
    )
    return notifier


def _args(**overrides) -> argparse.Namespace:
    return argparse.Namespace(
        **{"week": None, "rescore": False, "quiet": True, **overrides}
    )


def test_the_write_the_recompute_and_the_stamp_share_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three writes, in order, inside one block: the team totals are derived
    from the player rows this run wrote, and the stamp describes that recompute."""
    conn = FakeConn()
    _wire(monkeypatch, conn=conn)

    assert sleeper_cli.cmd_projections(_args()) == 0
    assert conn.events == [
        "begin",
        "upsert 2026w3 9400 rows",
        "recompute",
        "flag 100.00 flagged=False",
        "commit",
    ]


def test_the_season_row_is_looked_up_by_the_state_year_not_a_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SYNC_YEAR` is this league's season; the projection year is whatever the NFL
    is actually playing, and the two part company every January."""
    conn = FakeConn()
    _wire(monkeypatch, conn=conn, season=2027)

    sleeper_cli.cmd_projections(_args())

    assert conn.queries[0][1] == (2027,)


def test_a_thin_payload_never_opens_the_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal has to land before the transaction, not inside it: a run that
    opened one and rolled it back would still have to explain itself downstream."""
    conn = FakeConn()

    def boom(client, season, week, now):
        raise RuntimeError("sleeper returned too few projections for 2026 week 3: 4")

    _wire(monkeypatch, conn=conn, fetch=boom)

    with pytest.raises(RuntimeError):
        sleeper_cli.cmd_projections(_args())
    assert conn.events == []


def test_a_preseason_run_is_a_clean_no_op_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Off-season there is no slate to project, and refusing is not failing: the
    half-hourly job has to finish `succeeded` all winter, or the transition notes
    would announce a failure the first time and the run history would read as
    broken for months."""
    conn = FakeConn()

    def never(client, season, week, now):
        raise AssertionError("fetched during the preseason")

    notifier = _wire(monkeypatch, conn=conn, season_type="pre", fetch=never)

    assert sleeper_cli.cmd_projections(_args()) == 0
    assert conn.events == []
    assert notifier.notes == []
    assert capsys.readouterr().out == ""

    assert sleeper_cli.cmd_projections(_args(quiet=False)) == 0
    assert capsys.readouterr().out == "projections: skipped, season_type=pre\n"


def test_rescore_skips_the_fetch_and_still_recomputes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()

    def never(client, season, week, now):
        raise AssertionError("rescore refetched")

    _wire(monkeypatch, conn=conn, fetch=never)

    assert sleeper_cli.cmd_projections(_args(rescore=True)) == 0
    assert conn.events == [
        "begin", "rescore 2026w3", "recompute", "flag 100.00 flagged=False", "commit"
    ]


def test_coverage_falling_below_the_gate_posts_one_ops_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    notifier = _wire(monkeypatch, conn=conn, run_pct=Decimal("91.00"), before=CLEAR)

    sleeper_cli.cmd_projections(_args())

    assert conn.events[3] == "flag 91.00 flagged=True"
    assert notifier.notes == [
        "projections week 3: coverage 91.00% is below 95%; 18 teams marked provisional"
    ]


def test_coverage_still_below_the_gate_says_nothing_a_second_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This job fires every five minutes during a game window. A week that is short
    a projection stays short for hours; saying so once is a report, saying so forty
    times is noise nobody reads."""
    conn = FakeConn()
    notifier = _wire(
        monkeypatch,
        conn=conn,
        run_pct=Decimal("91.00"),
        before=WeekFlags(coverage_flagged=True, drift_flagged=False),
    )

    sleeper_cli.cmd_projections(_args())

    assert conn.events[3] == "flag 91.00 flagged=True"
    assert notifier.notes == []


def test_coverage_climbing_back_over_the_gate_posts_one_recovery_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    notifier = _wire(
        monkeypatch,
        conn=conn,
        run_pct=Decimal("97.00"),
        before=WeekFlags(coverage_flagged=True, drift_flagged=False),
    )

    sleeper_cli.cmd_projections(_args())

    assert notifier.notes == [
        "projections week 3: coverage recovered to 97.00%, at or above 95%"
    ]


def test_a_healthy_run_after_a_healthy_run_says_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    notifier = _wire(monkeypatch, conn=conn, before=CLEAR)

    sleeper_cli.cmd_projections(_args())

    assert notifier.notes == []


def test_the_drift_note_quotes_the_configured_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The number in the note is `DRIFT_POINTS`; a literal here would drift from the
    threshold that actually flagged the run the next time scoring is retuned."""
    conn = FakeConn()
    notifier = _wire(
        monkeypatch,
        conn=conn,
        report=SimpleNamespace(drift_flagged=True, drift_share=Decimal("0.0431")),
        before=CLEAR,
    )

    sleeper_cli.cmd_projections(_args())

    assert len(notifier.notes) == 1
    assert notifier.notes[0].startswith("projections week 3: 4.3% of scored players")
    assert f"more than {DRIFT_POINTS} points" in notifier.notes[0]


def test_drift_that_was_already_flagged_is_not_announced_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    notifier = _wire(
        monkeypatch,
        conn=conn,
        report=SimpleNamespace(drift_flagged=True, drift_share=Decimal("0.0431")),
        before=WeekFlags(coverage_flagged=False, drift_flagged=True),
    )

    sleeper_cli.cmd_projections(_args())

    assert notifier.notes == []


def test_drift_falling_back_under_the_threshold_posts_one_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ben fixes `seasons.scoring_settings` and reruns with `--rescore`; the channel
    should say the fix took, and then go quiet again."""
    conn = FakeConn()
    notifier = _wire(
        monkeypatch,
        conn=conn,
        report=SimpleNamespace(drift_flagged=False, drift_share=Decimal("0.0031")),
        before=WeekFlags(coverage_flagged=False, drift_flagged=True),
    )

    sleeper_cli.cmd_projections(_args(rescore=True))

    assert notifier.notes == [
        (
            "projections week 3: scoring drift cleared, 0.3% of scored players now "
            f"differ from the nearest Sleeper preset by more than {DRIFT_POINTS} points"
        )
    ]


def test_an_undeliverable_note_does_not_fail_a_good_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discord being unreachable is not a reason to record a run that wrote a full
    week of projections as `failed`."""
    conn = FakeConn()
    notifier = _wire(monkeypatch, conn=conn, run_pct=Decimal("91.00"), before=CLEAR)

    def boom(text: str) -> bool:
        raise ConnectionError("discord is unreachable")

    monkeypatch.setattr(notifier, "ops", boom)

    assert sleeper_cli.cmd_projections(_args()) == 0


def test_quiet_prints_nothing_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    conn = FakeConn()
    _wire(monkeypatch, conn=conn)

    sleeper_cli.cmd_projections(_args(quiet=True))
    assert capsys.readouterr().out == ""

    sleeper_cli.cmd_projections(_args(quiet=False))
    assert "projections: week 3, 9400 players (0 unscored), coverage 100.00%" in (
        capsys.readouterr().out
    )


def test_an_explicit_week_overrides_the_state_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    _wire(monkeypatch, conn=conn)

    sleeper_cli.cmd_projections(_args(week=1))

    assert "upsert 2026w1 9400 rows" in conn.events


def test_a_season_with_no_scoring_settings_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn(season_row=(4, {}))
    _wire(monkeypatch, conn=conn)

    with pytest.raises(ValueError):
        sleeper_cli.cmd_projections(_args())
    assert conn.events == []
