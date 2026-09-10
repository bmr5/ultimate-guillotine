"""Command wiring and the counts-only contract."""

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import psycopg
import pytest
from openpyxl import Workbook

from ultimate_guillotine.cli import history as history_cli
from ultimate_guillotine.history.repository import HistoryRowRejected

#: Every word the loader is allowed to print. A member name, a player name or a line of
#: chat would all fail this, which is the point.
ALLOWED_WORDS = {
    "catalog", "rows", "updated", "unresolved", "parties", "unmapped", "conditions",
    "results", "seasons", "names", "weeks", "with", "no", "count",
}

#: The records workbook, read by `load-results`. It is also the dues ledger, which is why
#: the counts-only assertion below matters more here than anywhere else.
WORKBOOK = str(Path(__file__).resolve().parents[4] / "history/league/ultimate-guillotine-records.xlsx")


def _assert_counts_only(text: str) -> None:
    for word in re.findall(r"[A-Za-z][A-Za-z'-]*", text):
        assert word in ALLOWED_WORDS, f"unexpected word in loader output: {word}"


def _record(**overrides) -> dict:
    base = {
        "id": "2025-001",
        "season": 2025,
        "week_or_date": {"week": 3, "date": "2025-09-23"},
        "type": "rental_flat",
        "structure": "flat_fee_rental",
        "parties": ["Nobody"],
        "assets": {
            "players": [], "positions": [], "faab": [],
            "return_conditions": ["SENTINEL owes a week"],
        },
        "faab_total": 0,
        "confidence": "high",
        "notes": "SENTINEL",
        "source_texts": ["SENTINEL"],
    }
    base.update(overrides)
    return base


class FakeRepo:
    """Records what the loader wrote, and can refuse a row the way Postgres would."""

    refuse: tuple[str, ...] = ()
    #: Ids a previous run in this test wrote. The real repository answers "updated" from
    #: Postgres' own `xmax = 0`; this is the same answer, one run later.
    written: ClassVar[set[str]] = set()
    #: The same, for the one row a season gets.
    seasons: ClassVar[set[int]] = set()
    #: Every season row written, so a test can look at what the command built.
    season_rows: ClassVar[list] = []

    def __init__(self, conn) -> None:
        self.rows: list = []

    def season_id_for(self, year: int) -> int | None:
        return None

    def upsert_catalog(self, row) -> str:
        if row.catalog_id in self.refuse:
            raise HistoryRowRejected(f"trade_catalog row {row.catalog_id} was refused")
        self.rows.append(row)
        outcome = "updated" if row.catalog_id in FakeRepo.written else "inserted"
        FakeRepo.written.add(row.catalog_id)
        return outcome

    def upsert_season_result(self, row) -> str:
        self.rows.append(row)
        FakeRepo.season_rows.append(row)
        outcome = "updated" if row.season in FakeRepo.seasons else "inserted"
        FakeRepo.seasons.add(row.season)
        return outcome


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch):
    """The loader's whole world, minus a database."""
    conn = SimpleNamespace(transaction=contextlib.nullcontext)
    monkeypatch.setattr(FakeRepo, "written", set())
    monkeypatch.setattr(FakeRepo, "seasons", set())
    monkeypatch.setattr(FakeRepo, "season_rows", [])
    monkeypatch.setattr(history_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    monkeypatch.setattr(history_cli, "HistoryRepository", FakeRepo)
    monkeypatch.setattr(
        history_cli, "MemberAliasRepository", lambda conn: SimpleNamespace(all_members=list)
    )
    monkeypatch.setattr(
        history_cli, "PlayerRepository", lambda conn: SimpleNamespace(all_active=list)
    )
    return conn


def _write(tmp_path: Path, *records: dict) -> str:
    path = tmp_path / "classification.json"
    path.write_text(json.dumps({"generated": "2026-09-09", "trades": list(records)}))
    return str(path)


def test_history_help_lists_load_catalog() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "history", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "load-catalog" in result.stdout
    assert "load-results" in result.stdout


def test_load_catalog_prints_counts_only(
    tmp_path: Path, stack, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, _record())

    exit_code = history_cli.cmd_load_catalog(argparse.Namespace(path=path))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.strip() == "catalog: 1 rows, 0 updated, 1 unresolved parties, 1 unmapped conditions"
    assert "SENTINEL" not in out
    _assert_counts_only(out)


def test_a_rerun_reports_the_rows_it_updated(
    tmp_path: Path, stack, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ben fixes an alias and reruns; "1 updated" says the table was corrected, not doubled."""
    path = _write(tmp_path, _record())

    assert history_cli.cmd_load_catalog(argparse.Namespace(path=path)) == 0
    capsys.readouterr()
    assert history_cli.cmd_load_catalog(argparse.Namespace(path=path)) == 0

    out = capsys.readouterr().out
    assert out.strip() == "catalog: 1 rows, 1 updated, 1 unresolved parties, 1 unmapped conditions"
    _assert_counts_only(out)


def test_load_catalog_exits_1_when_nothing_loaded(
    tmp_path: Path, stack, capsys: pytest.CaptureFixture[str]
) -> None:
    assert history_cli.cmd_load_catalog(argparse.Namespace(path=_write(tmp_path))) == 1
    _assert_counts_only(capsys.readouterr().out)


def test_a_refused_row_does_not_stop_the_rest(
    tmp_path: Path, stack, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One row the validators refuse is one row missing, not a failed run."""
    monkeypatch.setattr(FakeRepo, "refuse", ("2025-001",))
    path = _write(tmp_path, _record(), _record(id="2025-002", parties=[]))

    exit_code = history_cli.cmd_load_catalog(argparse.Namespace(path=path))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == (
        "catalog: 1 rows, 0 updated, 1 unresolved parties, 2 unmapped conditions"
    )
    # The refusal names the row's own id and never the payload that tripped it.
    assert "2025-001" in captured.err
    assert "SENTINEL" not in captured.err


def test_a_record_the_reader_refuses_does_not_stop_the_rest(
    tmp_path: Path, stack, capsys: pytest.CaptureFixture[str]
) -> None:
    """A record refused before it reaches the database is reported the same way.

    Its own counts go with it: the loader can say nothing about a record it would not
    read, so the line describes the file minus that record.
    """
    path = _write(
        tmp_path,
        _record(id="2025-003", structure="SENTINEL " * 20),
        _record(id="2025-004", parties=[]),
    )

    exit_code = history_cli.cmd_load_catalog(argparse.Namespace(path=path))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == (
        "catalog: 1 rows, 0 updated, 0 unresolved parties, 1 unmapped conditions"
    )
    assert "2025-003" in captured.err
    assert "SENTINEL" not in captured.err
    _assert_counts_only(captured.out)


def test_every_row_refused_exits_1(tmp_path: Path, stack, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeRepo, "refuse", ("2025-001",))
    assert history_cli.cmd_load_catalog(argparse.Namespace(path=_write(tmp_path, _record()))) == 1


@pytest.fixture
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    return url


def test_the_load_is_committed_and_not_left_open(
    tmp_path: Path, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real path, against the real database, because the failure mode is silent.

    `conn.transaction()` opens a transaction only when the connection has none; a read
    taken first opens one implicitly and turns the load into a savepoint inside it,
    which rolls back when the process ends -- after printing that every row loaded.
    """
    probe = "test-load-catalog-probe"
    with psycopg.connect(database_url) as loader_conn:
        monkeypatch.setattr(history_cli, "build_deps", lambda: SimpleNamespace(conn=loader_conn))
        path = _write(tmp_path, _record(id=probe))
        try:
            assert history_cli.cmd_load_catalog(argparse.Namespace(path=path)) == 0
            assert loader_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
            with psycopg.connect(database_url) as other, other.cursor() as cur:
                cur.execute(
                    "select count(*) from public.trade_catalog where catalog_id = %s", (probe,)
                )
                assert cur.fetchone()[0] == 1
        finally:
            with loader_conn.cursor() as cur:
                cur.execute("delete from public.trade_catalog where catalog_id = %s", (probe,))
            loader_conn.commit()


def test_load_results_prints_counts_only(stack, capsys: pytest.CaptureFixture[str]) -> None:
    """The real workbook, so the assertion is about the real file's champion cells."""
    exit_code = history_cli.cmd_load_results(argparse.Namespace(path=WORKBOOK, notes=[]))

    out = capsys.readouterr().out
    assert exit_code == 0
    # Six seasons on the Winners sheet; with no members loaded, six champions and one
    # second name resolve to nobody. The last field is 2024's week rows whose gulag
    # count is an uncached formula -- it falls to 0 once the file is recalculated.
    assert out.strip() == (
        "results: 6 seasons, 0 updated, 7 unresolved names, 11 weeks with no count"
    )
    _assert_counts_only(out)


def test_a_results_rerun_reports_the_seasons_it_updated(
    stack, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(path=WORKBOOK, notes=[])
    assert history_cli.cmd_load_results(args) == 0
    capsys.readouterr()
    assert history_cli.cmd_load_results(args) == 0

    out = capsys.readouterr().out
    assert out.strip() == (
        "results: 6 seasons, 6 updated, 7 unresolved names, 11 weeks with no count"
    )
    _assert_counts_only(out)


def test_load_results_carries_a_note_onto_its_season(stack) -> None:
    """`--notes` is the one text the command stores, and it is Ben's, not the workbook's."""
    history_cli.cmd_load_results(argparse.Namespace(path=WORKBOOK, notes=["2022=co-champions"]))

    by_season = {row.season: row for row in FakeRepo.season_rows}
    assert by_season[2022].notes == "co-champions"
    assert by_season[2024].notes is None
    # Nothing the workbook holds becomes a note.
    assert all(row.notes in (None, "co-champions") for row in FakeRepo.season_rows)
    # Nor a name: the rows are ids and counts.
    assert all(row.champion_member_id is None for row in FakeRepo.season_rows)


def test_notes_must_be_season_equals_text(stack) -> None:
    with pytest.raises(SystemExit, match="SEASON=TEXT"):
        history_cli.cmd_load_results(argparse.Namespace(path=WORKBOOK, notes=["co-champions"]))


def test_load_results_exits_1_when_nothing_loaded(
    tmp_path: Path, stack, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Winners sheet with no seasons on it is a load that did nothing, not a success."""
    book = Workbook()
    book.active.title = "Winners"
    path = tmp_path / "empty.xlsx"
    book.save(path)

    exit_code = history_cli.cmd_load_results(argparse.Namespace(path=str(path), notes=[]))

    assert exit_code == 1
    _assert_counts_only(capsys.readouterr().out)
