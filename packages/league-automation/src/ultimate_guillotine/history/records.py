"""Read the records workbook's public sheets.

The workbook is Ben's, and it is two documents in one file. Three sheets are league
record: who won, and how many teams went out each week. The rest is the commissioner's
own bookkeeping -- the 2025 sheet is a roster with a `paid` column, and the 2023 sheet
carries a signup block with handles and `paid` below its week grid. So this module does
not read a workbook; it reads three named sheets of one, through `public_sheet`, which
refuses every other name. A sheet Ben adds next August is invisible here until somebody
adds it to `PUBLIC_SHEETS` on purpose, which is the difference between a privacy rule
and a privacy habit.

What the sheets hold is thinner than what they look like. Almost every cell in both
week grids is a formula, and the file has never been through Excel's calculation engine
with its results saved, so `data_only=True` hands back `None` for all of them: the week
numbers past the first, the surviving-team columns, the running totals. The reader takes
what is literally in the file and leaves the rest null rather than recomputing the
spreadsheet -- a formula re-implemented in Python is a second source of truth that
drifts, and the pages would render the drift as history.

Nothing here resolves a name. `season_result_rows` maps the two champion cells through
the caller's label index and keeps ids; a name nobody answers to becomes a count. The
week grids never say *which* team went out, only how many, so `member_id` is null on
every entry this module builds -- named eliminations arrive from the Adjudicator, for
2026 onwards.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ultimate_guillotine.history.models import SeasonResultRow
from ultimate_guillotine.trades.names import normalize_name

#: The only sheets this module will open. Everything else in the file, named or not, is
#: refused by `public_sheet` rather than skipped by a caller who remembered to skip it.
PUBLIC_SHEETS = ("Winners", "2023", "2024")

#: `Winners`: headers on row 2, one row per season from row 3. `year` in column B,
#: `winner` in column C, and an unlabelled second name in column D that 2022 alone uses.
WINNERS_FIRST_ROW = 3
WINNERS_YEAR_COL = 2
WINNERS_CHAMPION_COL = 3
WINNERS_SECOND_COL = 4

#: `2024`: headers on row 3, one row per week from row 4 down to the row carrying the
#: `Winner` marker in column I. Week (B), Total Teams (C), Gulag Teams (D), Gen Pool
#: Teams (E), then the pair under "Teams Eliminated this week from:" -- Gulag (F) and
#: Pool (G) -- and Surviving Teams (H).
#:
#: Only B4 and C4 hold a typed week and team count; B5 down is `=B4+1` and C5 down is
#: `=H4`, both uncached. So the week is the row's own position and nothing else, and the
#: team count is read once, off the row that states it. Column H is uncached throughout,
#: which is why no entry carries `remaining`.
GRID_2024_FIRST_ROW = 4
GRID_2024_TOTAL_COL = 3
GRID_2024_GULAG_OUT_COL = 6
GRID_2024_POOL_OUT_COL = 7
GRID_2024_WINNER_COL = 9

#: `2023`, upper grid: a transposed week table on rows 3-9 (Week, Safe, Gulag,
#: Gladiator, Cut, Alive, Total) with weeks running across columns C to S and the
#: `Winner!` marker in T. Its Cut row is a *cumulative* formula (`=C7+sum(C5:C6)`) with
#: no cached value, so it states no per-week elimination count at all. Only its Total
#: row is read here, and only to check it against the summary grid.
GRID_2023_TOTAL_ROW = 9
GRID_2023_TOTAL_COL = 3

#: `2023`, summary grid: headers on row 16, weeks 11 to 17 on rows 17-23, and the
#: `Winner` marker in the week column of row 24, which is where the read stops. Week (M),
#: Total Teams (N), Teams in Gulag (O), Teams sent to Gulag (P), Teams cut at EOW (Q),
#: Teams going into next week (R -- blank throughout, hence no `remaining`).
#:
#: Everything below row 24 is the signup block: handles, seats and `paid`. It is outside
#: this range and there is no code path that widens the range at runtime.
SUMMARY_2023_FIRST_ROW = 17
SUMMARY_2023_LAST_ROW = 23
SUMMARY_2023_WEEK_COL = 13
SUMMARY_2023_TOTAL_COL = 14
SUMMARY_2023_CUT_COL = 17


class SheetRefused(LookupError):
    """A sheet outside the allowlist. Names neither the sheet nor a cell of it."""


@dataclass(frozen=True)
class WinnerRow:
    """One row of the `Winners` sheet: the year and the names beside it, trimmed."""

    year: int
    champion_name: str
    second_name: str | None


def public_sheet(workbook, name: str):
    """The one door onto a sheet, and the only one this module uses.

    The refusal deliberately names nothing. A message reading "2025 is not public" would
    be harmless, but the habit of interpolating whatever the caller asked for into an
    error is how a cell value ends up in a log, so the door says only what it does.
    """
    if name not in PUBLIC_SHEETS:
        raise SheetRefused("the records reader opens only the workbook's public sheets")
    return workbook[name]


def _int(value: Any) -> int | None:
    """A whole number the cell actually holds, or nothing.

    `True` is not a 1 however much Python says so, and an uncached formula is `None`.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    return int(text) if text.lstrip("-").isdigit() else None


def _text(value: Any) -> str | None:
    """A trimmed non-empty string, or nothing. The workbook pads several names."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _entry(week: int, order: int, gulag_out: int | None, pool_out: int | None) -> dict[str, Any]:
    """One elimination entry in the shape `season_results_eliminations_ok` allows.

    `member_id` and `note` are null and stay null: the grids record how many teams went
    out, never which, and a caption written from a workbook cell would be workbook text
    on a public page.
    """
    return {
        "week": week,
        "order": order,
        "member_id": None,
        "gulag_out": gulag_out,
        "pool_out": pool_out,
        "note": None,
    }


def read_winners(workbook) -> list[WinnerRow]:
    """Every row of the `Winners` sheet, oldest first.

    A row without both a year and a champion is not a season -- it is the header, or a
    blank the sheet keeps for next year -- and is skipped.
    """
    sheet = public_sheet(workbook, "Winners")
    winners: list[WinnerRow] = []
    for row in range(WINNERS_FIRST_ROW, sheet.max_row + 1):
        year = _int(sheet.cell(row=row, column=WINNERS_YEAR_COL).value)
        champion = _text(sheet.cell(row=row, column=WINNERS_CHAMPION_COL).value)
        if year is None or champion is None:
            continue
        second = _text(sheet.cell(row=row, column=WINNERS_SECOND_COL).value)
        winners.append(WinnerRow(year=year, champion_name=champion, second_name=second))
    return winners


def _eliminations_2024(sheet) -> list[dict[str, Any]]:
    """Rows 4 down to the `Winner` row, one entry per week.

    The week is the row's distance from the first, never the previous entry's week plus
    one: a skipped row would otherwise renumber every week after it, and the renumbering
    would look exactly like data.
    """
    entries: list[dict[str, Any]] = []
    for row in range(GRID_2024_FIRST_ROW, sheet.max_row + 1):
        gulag_out = _int(sheet.cell(row=row, column=GRID_2024_GULAG_OUT_COL).value)
        pool_out = _int(sheet.cell(row=row, column=GRID_2024_POOL_OUT_COL).value)
        if gulag_out is not None or pool_out is not None:
            week = row - GRID_2024_FIRST_ROW + 1
            entries.append(_entry(week, len(entries) + 1, gulag_out, pool_out))
        # The `Winner` cell sits on the season's last week. Past it the sheet is over.
        if _text(sheet.cell(row=row, column=GRID_2024_WINNER_COL).value):
            break
    return entries


def _eliminations_2023(sheet) -> list[dict[str, Any]]:
    """The summary grid's weeks 11-17, which is every elimination count the sheet states.

    2023 ran without a general pool -- a team was safe, in the gulag, or cut -- so the
    "Teams cut at EOW" column is the count of teams that went out of the gulag, and
    `pool_out` stays null rather than being filled with a zero the sheet never wrote.

    The read stops at the first row whose week cell is not a number, which is row 24's
    `Winner` marker. That is also the fence: the signup block starts three rows later.
    """
    entries: list[dict[str, Any]] = []
    for row in range(SUMMARY_2023_FIRST_ROW, SUMMARY_2023_LAST_ROW + 1):
        week = _int(sheet.cell(row=row, column=SUMMARY_2023_WEEK_COL).value)
        if week is None:
            break
        cut = _int(sheet.cell(row=row, column=SUMMARY_2023_CUT_COL).value)
        if cut is None:
            continue
        entries.append(_entry(week, len(entries) + 1, gulag_out=cut, pool_out=None))
    return entries


def read_eliminations(workbook, season: int) -> list[dict[str, Any]]:
    """The season's week grid as ordered count entries, or nothing for a season with no sheet.

    Both grids record how many teams went out, never which, so `member_id` is null on
    every entry and the page renders counts. The seasons before 2023 have no sheet at
    all: their row carries a champion and an empty grid, which is the truth about what
    the workbook remembers of them.
    """
    name = str(season)
    if name not in PUBLIC_SHEETS or name not in workbook.sheetnames:
        return []
    sheet = public_sheet(workbook, name)
    return _eliminations_2024(sheet) if season == 2024 else _eliminations_2023(sheet)


def _team_count(workbook, season: int) -> int | None:
    """How many teams the season started with, where the sheet says so once and plainly.

    2024 states it in the first row of its grid. 2023 has two grids that disagree -- the
    upper one's total is an uncached formula and the summary grid's is a mid-season
    count -- so the row says nothing rather than publishing whichever one was easier to
    read. A season with no sheet has no count.
    """
    name = str(season)
    if name not in PUBLIC_SHEETS or name not in workbook.sheetnames:
        return None
    sheet = public_sheet(workbook, name)
    if season == 2024:
        return _int(sheet.cell(row=GRID_2024_FIRST_ROW, column=GRID_2024_TOTAL_COL).value)
    grid = _int(sheet.cell(row=GRID_2023_TOTAL_ROW, column=GRID_2023_TOTAL_COL).value)
    summary = _int(sheet.cell(row=SUMMARY_2023_FIRST_ROW, column=SUMMARY_2023_TOTAL_COL).value)
    return grid if grid is not None and grid == summary else None


def season_result_rows(
    path: Path | str,
    index: dict[str, int | None],
    notes: dict[int, str],
    loaded_at: datetime,
) -> tuple[list[SeasonResultRow], int]:
    """Build one row per season in `Winners`, plus the count of names nobody matched.

    A name that does not resolve leaves its column null and increments a count; the
    workbook's spelling is never stored, so an unresolved champion is a number Ben can
    fix with an alias and a rerun rather than a name sitting in a public table. A label
    two members answer to is unresolved for the same reason it is in the trade catalog:
    the wrong champion published permanently is worse than a count.

    `notes` is the operator's own text, passed in by the command; no cell of the
    workbook reaches that column.
    """
    workbook = load_workbook(path, data_only=True)
    try:
        rows: list[SeasonResultRow] = []
        unresolved_total = 0
        for winner in read_winners(workbook):
            champion_id = index.get(normalize_name(winner.champion_name))
            second_id = (
                index.get(normalize_name(winner.second_name)) if winner.second_name else None
            )
            unresolved = int(champion_id is None) + int(
                winner.second_name is not None and second_id is None
            )
            unresolved_total += unresolved
            rows.append(
                SeasonResultRow(
                    season=winner.year,
                    season_id=None,
                    champion_member_id=champion_id,
                    # Column D is a co-champion: 2022 was shared, and the sheet records
                    # it by putting a second name beside the first with no other mark.
                    co_champion_member_id=second_id,
                    runner_up_member_id=None,
                    third_member_id=None,
                    team_count=_team_count(workbook, winner.year),
                    eliminations=read_eliminations(workbook, winner.year),
                    notes=notes.get(winner.year),
                    unresolved_names=unresolved,
                    loaded_at=loaded_at,
                )
            )
        return rows, unresolved_total
    finally:
        workbook.close()
