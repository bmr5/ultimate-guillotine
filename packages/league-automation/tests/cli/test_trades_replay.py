import argparse
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from ultimate_guillotine.cli import trades as trades_cli
from ultimate_guillotine.cli.trades import load_replay_rows, replay_rows
from ultimate_guillotine.config import Settings

TERMS = "Member01 swaps Player Alpha for Player Beta with Member02"


def test_load_replay_rows_reads_terms_and_parties(tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Date", "Week", "Terms", "Parties"])
    ws.append(["2025-09-07", "Week 1", TERMS, "Member01", "Member02"])
    ws.append(["2025-09-08", "Week 1", None, None])
    path = tmp_path / "c.xlsx"
    wb.save(path)

    rows = load_replay_rows(path)

    assert rows == [("Week 1", f"🚨 {TERMS}", ["Member01", "Member02"])]


def test_replay_rows_prints_one_line_per_row_and_a_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The loop decides `not-a-candidate` itself; the pipeline sees the rest.

    Outcomes outside the four fixed counters (`revised`, `failed` here) are
    appended to the summary only when they happened, so the counters always add
    up to the row count.
    """
    rows = [
        ("Week 1", f"🚨 {TERMS}", ["Member01", "Member02"]),
        ("Week 2", "🚨 Member03 sends Player Gamma to Member04", ["Member03"]),
        ("Week 3", "Congrats on the win", []),
        ("Week 4", "🚨 Member05 sends Player Delta to Member06", ["Member05"]),
        ("Week 5", "🚨 Member07 sends Player Epsilon to Member08", ["Member07"]),
    ]
    seen: list[tuple[int, str]] = []
    outcomes = iter(["created", "clarification: I don't know Player Gamma", "revised", "failed"])

    def run_row(index: int, text: str) -> str:
        seen.append((index, text))
        return next(outcomes)

    exit_code = replay_rows(rows, run_row)

    assert exit_code == 0
    assert seen == [(1, rows[0][1]), (2, rows[1][1]), (4, rows[3][1]), (5, rows[4][1])]
    assert capsys.readouterr().out == (
        "row 1: created\n"
        "row 2: clarification: I don't know Player Gamma\n"
        "row 3: not-a-candidate\n"
        "row 4: revised\n"
        "row 5: failed\n"
        "replay: 5 rows, created 1, duplicate 0, clarification 1, not-a-candidate 1, "
        "revised 1, failed 1\n"
    )


class NoSeasonCursor:
    """A cursor whose `public.seasons` lookup comes back empty."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None) -> None:
        pass

    def fetchone(self):
        return None


class NoSeasonConn:
    def cursor(self) -> NoSeasonCursor:
        return NoSeasonCursor()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://x:y@example.invalid/db",
        delivery_mode="disabled",
        _env_file=None,
    )


def test_replay_write_mode_refuses_without_a_season_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every accept hangs off the season row, so without it the replay would burn
    one model call per row to fail on all of them."""
    wb = openpyxl.Workbook()
    wb.active.append(["Date", "Week", "Terms", "Parties"])
    wb.active.append(["2025-09-07", "Week 1", TERMS, "Member01", "Member02"])
    path = tmp_path / "c.xlsx"
    wb.save(path)

    settings = _settings()
    deps = SimpleNamespace(settings=settings, conn=NoSeasonConn(), client=None, notifier=None)
    monkeypatch.setattr(trades_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(trades_cli, "build_deps", lambda: deps)
    monkeypatch.setattr(trades_cli, "build_ai", lambda _deps: None)

    exit_code = trades_cli.cmd_replay(argparse.Namespace(xlsx=str(path), limit=None, dry_run=False))

    assert exit_code == 2
    assert capsys.readouterr().out == "no public.seasons row for 2025; insert it first\n"
