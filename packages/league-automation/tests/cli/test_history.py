"""Command wiring and the counts-only contract."""

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import psycopg
import pytest
from openpyxl import Workbook

from ultimate_guillotine.cli import history as history_cli
from ultimate_guillotine.history.models import SeasonResultRow
from ultimate_guillotine.history.repository import HistoryRepository, HistoryRowRejected
from ultimate_guillotine.trades.models import MemberRef

#: Every word the loader is allowed to print. A member name, a player name or a line of
#: chat would all fail this, which is the point.
ALLOWED_WORDS = {
    "catalog", "rows", "updated", "unresolved", "parties", "unmapped", "conditions",
    "results", "seasons", "names", "weeks", "with", "no", "count",
    "result", "season", "created",
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
        # Loaded into the row by Ben's ruling of 2026-09-10 -- and still never printed. The
        # sentinel is spelled apart from the private one so the assertions below can tell a
        # field that must not exist from a field that must not be echoed.
        "source_texts": ["ANNOUNCEMENT-SENTINEL"],
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
    #: The eliminations each season's row is carrying, which is what `set-result` reads
    #: back rather than blanking a week grid in order to set a champion.
    stored_eliminations: ClassVar[dict[int, list]] = {}

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

    def eliminations_for(self, season: int) -> list:
        return list(FakeRepo.stored_eliminations.get(season, []))

    def upsert_season_result(self, row) -> str:
        self.rows.append(row)
        FakeRepo.season_rows.append(row)
        FakeRepo.stored_eliminations[row.season] = list(row.eliminations)
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
    monkeypatch.setattr(FakeRepo, "stored_eliminations", {})
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
    # Neither the analyst's note nor the announcement the loader *did* store: a field being
    # published on a page is not a licence to print it into a terminal Ben shares his screen on.
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


#: The username Ben would type. A sentinel, spelled so it could not be anybody's real
#: handle, because the assertions below check that it never reaches stdout or stderr.
CHAMPION = "SENTINEL-CHAMPION"
CO_CHAMPION = "SENTINEL-CO-CHAMPION"

#: A season nobody played, so a rerun of the real loaders against the local stack cannot
#: turn a passing test red by having written the row first.
HAND_SET_SEASON = 2097


def _seed_member(conn) -> int:
    """One real `public.members` row, so the row's foreign keys have something to point at."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name, nickname) values (%s, %s) returning id",
            ("Member99", CHAMPION),
        )
        return cur.fetchone()[0]


def _member(member_id: int, alias: str) -> MemberRef:
    """One member the label index will match `alias` to, and nothing else."""
    return MemberRef(member_id, f"Member{member_id:02d}", (alias,))


def _knows(monkeypatch: pytest.MonkeyPatch, *members: MemberRef) -> None:
    """Point the command's member lookup at exactly these people."""
    monkeypatch.setattr(
        history_cli,
        "MemberAliasRepository",
        lambda conn: SimpleNamespace(all_members=lambda: list(members)),
    )


def _set_args(**overrides) -> argparse.Namespace:
    base = {
        "season": HAND_SET_SEASON,
        "champion": CHAMPION,
        "co_champion": None,
        "runner_up": None,
        "third": None,
        "team_count": None,
        "notes": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_set_result_is_in_the_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "history", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "set-result" in result.stdout


def test_set_result_creates_a_season_the_workbook_does_not_cover(
    stack, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 2025 case: a season Ben won, on no public sheet, written by hand."""
    _knows(monkeypatch, _member(1, CHAMPION), _member(2, CO_CHAMPION))

    exit_code = history_cli.cmd_set_result(
        _set_args(co_champion=CO_CHAMPION, team_count=20, notes="a season on no sheet")
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert out.strip() == f"result: season {HAND_SET_SEASON} created"
    # Counts and the season, and no part of what Ben typed to name the people in it.
    assert CHAMPION not in out
    assert CO_CHAMPION not in out
    _assert_counts_only(out)

    (row,) = FakeRepo.season_rows
    assert (row.champion_member_id, row.co_champion_member_id) == (1, 2)
    assert (row.runner_up_member_id, row.third_member_id) == (None, None)
    assert row.team_count == 20
    assert row.notes == "a season on no sheet"
    # Nothing was read, so nothing was unresolved -- the command refuses to write a row
    # it could not resolve at all, so the only number this column can carry is zero.
    assert row.unresolved_names == 0
    assert row.eliminations == []


def test_set_result_resolves_a_nickname_the_way_the_loaders_do(
    stack, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build_label_index` matches an alias, a nickname or the Sleeper display name."""
    member = MemberRef(7, "Member07", (), nickname="Sentinel Nickname")
    _knows(monkeypatch, member)

    assert history_cli.cmd_set_result(_set_args(champion="  sentinel   NICKNAME!  ")) == 0

    assert FakeRepo.season_rows[0].champion_member_id == 7
    _assert_counts_only(capsys.readouterr().out)


def test_set_result_rerun_updates_the_one_row(
    stack, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ben adds a runner-up he forgot; the season is corrected, not doubled."""
    _knows(monkeypatch, _member(1, CHAMPION), _member(2, CO_CHAMPION))

    assert history_cli.cmd_set_result(_set_args()) == 0
    capsys.readouterr()
    assert history_cli.cmd_set_result(_set_args(runner_up=CO_CHAMPION)) == 0

    out = capsys.readouterr().out
    assert out.strip() == f"result: season {HAND_SET_SEASON} updated"
    assert [row.season for row in FakeRepo.season_rows] == [HAND_SET_SEASON] * 2
    assert FakeRepo.season_rows[1].runner_up_member_id == 2
    _assert_counts_only(out)


def test_set_result_keeps_the_weeks_a_load_already_wrote(
    stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rerun to name a champion must not blank a season's week grid to do it."""
    _knows(monkeypatch, _member(1, CHAMPION))
    weeks = [
        {"week": 2, "order": 1, "member_id": None, "gulag_out": 2, "pool_out": 0, "note": None}
    ]
    monkeypatch.setitem(FakeRepo.stored_eliminations, HAND_SET_SEASON, weeks)

    assert history_cli.cmd_set_result(_set_args()) == 0

    assert FakeRepo.season_rows[0].eliminations == weeks


def test_set_result_exits_1_on_a_name_nobody_answers_to(
    stack, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A misspelt username is a season with no champion, which is worse than no season."""
    _knows(monkeypatch)

    exit_code = history_cli.cmd_set_result(_set_args())

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "add an alias" in captured.err
    # The whole point: the failure says a name did not resolve without saying which.
    assert CHAMPION not in captured.err
    assert captured.out == ""
    # And nothing was written -- a half-named season is not published while Ben looks
    # for the spelling.
    assert FakeRepo.season_rows == []


def test_set_result_exits_1_on_a_label_two_members_answer_to(
    stack, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ambiguous is unresolved: the wrong champion published permanently is worse."""
    _knows(monkeypatch, _member(1, CHAMPION), _member(2, CHAMPION))

    assert history_cli.cmd_set_result(_set_args()) == 1

    captured = capsys.readouterr()
    assert CHAMPION not in captured.err
    assert FakeRepo.season_rows == []


def test_set_result_refuses_a_later_placing_before_writing_anything(
    stack, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The champion resolves and the third-place name does not; the row still is not written."""
    _knows(monkeypatch, _member(1, CHAMPION))

    assert history_cli.cmd_set_result(_set_args(third="SENTINEL-NOBODY")) == 1

    assert "SENTINEL-NOBODY" not in capsys.readouterr().err
    assert FakeRepo.season_rows == []


def _winners_workbook(tmp_path: Path, *years: int) -> str:
    """A `Winners` sheet holding exactly these seasons: year in B, champion in C, from row 3."""
    book = Workbook()
    book.active.title = "Winners"
    for offset, year in enumerate(years):
        book.active.cell(row=3 + offset, column=2, value=year)
        book.active.cell(row=3 + offset, column=3, value=f"SENTINEL-WINNER-{year}")
    path = tmp_path / "winners.xlsx"
    book.save(path)
    return str(path)


def test_load_results_leaves_a_hand_set_season_alone(
    tmp_path: Path, conn, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim the whole command rests on, against the real table.

    `load-results` upserts one row per season on the `Winners` sheet and touches nothing
    else, so the season Ben set by hand -- the one the sheet has never heard of -- is
    still there, unchanged, after a rerun. Checked as a whole-row comparison rather than
    a count, because a clobber that reset the champion to null would pass a count.
    """
    monkeypatch.setattr(history_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    member_id = _seed_member(conn)
    _knows(monkeypatch, MemberRef(member_id, "Member99", (), nickname=CHAMPION))
    read_back = (
        "select to_jsonb(t) - 'id' - 'created_at' from public.season_results t where season = %s"
    )

    assert history_cli.cmd_set_result(_set_args(team_count=20, notes="set by hand")) == 0
    with conn.cursor() as cur:
        cur.execute(read_back, (HAND_SET_SEASON,))
        before = cur.fetchone()[0]
    assert before["champion_member_id"] == member_id

    # A workbook covering one other season, which is the shape of the real one: the
    # `Winners` sheet is a year behind the league and never mentions the hand-set season.
    path = _winners_workbook(tmp_path, 2096)
    assert history_cli.cmd_load_results(argparse.Namespace(path=path, notes=[])) == 0

    with conn.cursor() as cur:
        cur.execute(read_back, (HAND_SET_SEASON,))
        assert cur.fetchone()[0] == before
        cur.execute("select count(*) from public.season_results where season = 2096")
        assert cur.fetchone()[0] == 1
    _assert_counts_only(capsys.readouterr().out)


def test_set_result_writes_the_row_the_pages_read(
    conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real path against the real table, including the eliminations it must preserve."""
    monkeypatch.setattr(history_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    member_id = _seed_member(conn)
    _knows(monkeypatch, MemberRef(member_id, "Member99", (), nickname=CHAMPION))

    # A season a `load-results` run had already written a week grid onto.
    weeks = [
        {"week": 2, "order": 1, "member_id": None, "gulag_out": 2, "pool_out": 0, "note": None}
    ]
    HistoryRepository(conn).upsert_season_result(
        SeasonResultRow(
            season=HAND_SET_SEASON,
            season_id=None,
            champion_member_id=None,
            co_champion_member_id=None,
            runner_up_member_id=None,
            third_member_id=None,
            team_count=None,
            eliminations=weeks,
            loaded_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        )
    )

    assert history_cli.cmd_set_result(_set_args(team_count=20)) == 0

    with conn.cursor() as cur:
        cur.execute(
            "select champion_member_id, team_count, eliminations, unresolved_names"
            " from public.season_results where season = %s",
            (HAND_SET_SEASON,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == (member_id, 20, weeks, 0)
