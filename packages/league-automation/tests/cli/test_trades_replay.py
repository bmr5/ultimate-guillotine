from pathlib import Path

import pytest

from ultimate_guillotine.cli.trades import load_replay_rows, replay_rows

TERMS = "Member01 swaps Player Alpha for Player Beta with Member02"


def test_load_replay_rows_reads_terms_and_parties(tmp_path: Path) -> None:
    import openpyxl

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
    outcomes = iter(
        ["created", "clarification: I don't know Player Gamma", "revised", "failed"]
    )

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
