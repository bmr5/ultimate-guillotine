"""The workbook is also the commissioner's dues ledger. These tests are the fence.

Two sheets of the file are a roster: the 2025 sheet carries a `paid` column, and the
2023 sheet carries a signup block with handles and `paid` below its week grid. So the
first tests here are not about results at all -- they are about which sheets and which
rows the reader is even allowed to open, asserted against static sentinels rather than
against anything read out of the private sheet, because a test that quoted a private
cell to prove it stayed private would be the leak it was written to prevent.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from psycopg.types.json import Jsonb

from ultimate_guillotine.history.records import (
    PUBLIC_SHEETS,
    SheetRefused,
    public_sheet,
    read_eliminations,
    read_winners,
    season_result_rows,
)

WORKBOOK = Path(__file__).resolve().parents[4] / "history/league/ultimate-guillotine-records.xlsx"
LOADED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

#: The dues sheet, named here as a literal and nowhere else. Nothing in this file reads a
#: cell of it, so no assertion can carry one into a failure message.
DUES_SHEET = "2025"


@pytest.fixture
def workbook():
    book = load_workbook(WORKBOOK, data_only=True)
    yield book
    book.close()


class SheetSpy:
    """A workbook that records every sheet asked for. The whole point is the record."""

    def __init__(self, real) -> None:
        self._real = real
        self.opened: list[str] = []

    @property
    def sheetnames(self) -> list[str]:
        return self._real.sheetnames

    def __getitem__(self, name: str):
        self.opened.append(name)
        return self._real[name]

    def close(self) -> None:
        self._real.close()


def test_public_sheets_is_a_hard_allowlist() -> None:
    assert PUBLIC_SHEETS == ("Winners", "2023", "2024")
    assert DUES_SHEET not in PUBLIC_SHEETS


def test_the_dues_sheet_cannot_be_opened(workbook) -> None:
    """The allowlist is a door, not a convention: asking for the sheet raises."""
    assert DUES_SHEET in workbook.sheetnames

    with pytest.raises(SheetRefused):
        public_sheet(workbook, DUES_SHEET)

    # The refusal says what the reader does, and names no sheet and no cell.
    with pytest.raises(SheetRefused) as excinfo:
        public_sheet(workbook, DUES_SHEET)
    assert DUES_SHEET not in str(excinfo.value)


def test_a_whole_load_opens_only_the_allowlisted_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not "the loader means to skip 2025" but "the loader never asked for it"."""
    spy = SheetSpy(load_workbook(WORKBOOK, data_only=True))
    monkeypatch.setattr(
        "ultimate_guillotine.history.records.load_workbook", lambda *a, **k: spy
    )

    season_result_rows(WORKBOOK, index={}, notes={}, loaded_at=LOADED_AT)

    assert spy.opened, "the reader opened no sheet at all"
    assert set(spy.opened) <= set(PUBLIC_SHEETS), "a sheet outside the allowlist was opened"


def test_winners_reads_year_and_champion_columns(workbook) -> None:
    winners = read_winners(workbook)

    assert [winner.year for winner in winners] == [2019, 2020, 2021, 2022, 2023, 2024]
    # Column D carries a second name for 2022 alone; every other row leaves it empty.
    assert [winner.year for winner in winners if winner.second_name] == [2022]
    assert all(winner.champion_name for winner in winners)
    # Whatever the cell's padding, the name the index is asked about is trimmed.
    assert all(winner.champion_name == winner.champion_name.strip() for winner in winners)


def test_2024_eliminations_are_counts_with_no_member_id(workbook) -> None:
    entries = read_eliminations(workbook, 2024)

    assert entries, "the 2024 sheet carries a week grid"
    assert all(entry["member_id"] is None for entry in entries)
    assert [entry["order"] for entry in entries] == list(range(1, len(entries) + 1))
    # `remaining` is absent: the sheet's Surviving Teams column is a formula with no
    # cached value, so there is nothing to put there and nothing is invented.
    assert {"week", "order", "member_id", "gulag_out", "pool_out", "note"} == set(entries[0])
    assert all(entry["note"] is None for entry in entries)


def test_2024_weeks_come_from_the_row_not_from_a_running_count(workbook) -> None:
    """Only B4 holds a week number; B5 down is `=B4+1`, uncached. The row is the week."""
    entries = read_eliminations(workbook, 2024)

    assert [entry["week"] for entry in entries] == list(range(1, 18))


def test_2023_eliminations_come_from_the_summary_grid(workbook) -> None:
    """The upper grid's cut row is a cumulative formula; the summary grid holds the counts."""
    entries = read_eliminations(workbook, 2023)

    assert [entry["week"] for entry in entries] == [11, 12, 13, 14, 15, 16, 17]
    assert [entry["order"] for entry in entries] == list(range(1, 8))
    assert all(entry["member_id"] is None for entry in entries)
    # 2023 had no gen pool: every cut came out of the gulag.
    assert all(entry["pool_out"] is None for entry in entries)
    assert all(entry["gulag_out"] is not None for entry in entries)


def test_a_season_with_no_sheet_has_no_eliminations(workbook) -> None:
    assert read_eliminations(workbook, 2019) == []
    assert read_eliminations(workbook, 2025) == []


def test_unresolved_champion_is_counted_not_named() -> None:
    rows, unresolved = season_result_rows(WORKBOOK, index={}, notes={}, loaded_at=LOADED_AT)
    by_season = {row.season: row for row in rows}

    assert unresolved == 7, "six champions and one second name, none of them resolvable"
    assert all(row.champion_member_id is None for row in rows)
    assert all(row.co_champion_member_id is None for row in rows)
    assert by_season[2024].unresolved_names == 1
    assert by_season[2022].unresolved_names == 2


def test_a_resolved_champion_is_an_id_and_costs_no_count(workbook) -> None:
    champion = read_winners(workbook)[-1].champion_name
    index = {champion.strip().lower(): 7}

    rows, unresolved = season_result_rows(WORKBOOK, index=index, notes={}, loaded_at=LOADED_AT)
    by_season = {row.season: row for row in rows}

    assert by_season[2024].champion_member_id == 7
    assert by_season[2024].unresolved_names == 0
    assert unresolved == 5


def test_team_count_is_read_only_where_the_sheet_states_it() -> None:
    rows, _ = season_result_rows(WORKBOOK, index={}, notes={}, loaded_at=LOADED_AT)
    by_season = {row.season: row for row in rows}

    assert by_season[2024].team_count == 19
    # The 2023 sheet's two grids disagree about how many teams there were, so the row
    # says nothing rather than picking one.
    assert by_season[2023].team_count is None
    assert by_season[2019].team_count is None


def test_a_note_is_attached_to_its_season() -> None:
    rows, _ = season_result_rows(
        WORKBOOK, index={}, notes={2022: "co-champions"}, loaded_at=LOADED_AT
    )
    by_season = {row.season: row for row in rows}

    assert by_season[2022].notes == "co-champions"
    assert by_season[2023].notes is None


def test_a_workbook_with_no_winners_yields_no_rows(tmp_path: Path) -> None:
    """Exit-1 territory for the command: an empty sheet is not a season."""
    book = Workbook()
    book.active.title = "Winners"
    path = tmp_path / "empty.xlsx"
    book.save(path)

    rows, unresolved = season_result_rows(path, index={}, notes={}, loaded_at=LOADED_AT)

    assert rows == []
    assert unresolved == 0


def test_every_elimination_entry_passes_the_databases_validator(conn) -> None:
    """The jsonb shape is the database's rule; this asserts the reader obeys it."""
    rows, _ = season_result_rows(WORKBOOK, index={}, notes={}, loaded_at=LOADED_AT)

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                "select public.season_results_eliminations_ok(%s)", (Jsonb(row.eliminations),)
            )
            assert cur.fetchone()[0] is True
