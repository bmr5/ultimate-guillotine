import argparse
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ultimate_guillotine.ai.structured import AIInvalidOutput
from ultimate_guillotine.cli import trades as trades_cli
from ultimate_guillotine.trades.resolve import MemberRef


def test_trades_help_lists_commands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "trades", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for name in ("extract", "list", "retry", "replay"):
        assert name in result.stdout


def _trade(code: str = "T-2026-001") -> dict:
    return {
        "trade_id": 1,
        "trade_code": code,
        "status": "accepted",
        "revision": 1,
        "effective_week": 2,
        "terms": {"parties": [{"display_name": "Member01"}, {"display_name": "Member02"}]},
    }


def test_list_prints_a_header_over_the_rows(capsys: pytest.CaptureFixture[str]) -> None:
    trades_cli.print_trades([_trade()])
    assert capsys.readouterr().out == (
        "code  status  rev  week  parties\nT-2026-001  accepted  1  2  Member01, Member02\n"
    )


def test_list_says_so_when_there_is_nothing_to_show(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty output would read as a failed command in `#guillotine-ops`."""
    trades_cli.print_trades([])
    assert capsys.readouterr().out == "no trades recorded\n"


def test_limit_must_be_a_positive_int() -> None:
    assert trades_cli.positive_int("3") == 3
    for bad in ("0", "-1"):
        with pytest.raises(argparse.ArgumentTypeError):
            trades_cli.positive_int(bad)


def test_the_list_parser_rejects_a_zero_limit() -> None:
    parser = argparse.ArgumentParser()
    trades_cli.register(parser.add_subparsers())
    with pytest.raises(SystemExit):
        parser.parse_args(["trades", "list", "--limit", "0"])


class _ExplodingConn:
    """cmd_extract's repositories are all stubbed, so the connection is only a token."""


def test_extract_reports_a_rejected_model_answer_by_class_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A model that will not produce the schema is an operator problem, not a
    traceback -- and the pydantic error it chains quotes the announcement back, so
    only the class name is printed."""
    deps = SimpleNamespace(settings=SimpleNamespace(sleeper_league_id="1"), conn=_ExplodingConn())
    monkeypatch.setattr(trades_cli, "build_deps", lambda: deps)
    monkeypatch.setattr(trades_cli, "build_ai", lambda _deps: None)
    monkeypatch.setattr(
        trades_cli, "SeasonRepository", lambda _conn: SimpleNamespace(current=lambda: 2026)
    )
    monkeypatch.setattr(
        trades_cli, "MemberAliasRepository", lambda _conn: SimpleNamespace(all_members=list)
    )
    monkeypatch.setattr(
        trades_cli, "PlayerRepository", lambda _conn: SimpleNamespace(all_active=list)
    )

    def explode(*args, **kwargs):
        raise AIInvalidOutput("ValidationError")

    monkeypatch.setattr(trades_cli, "dry_run_pipeline", explode)

    exit_code = trades_cli.cmd_extract(
        argparse.Namespace(
            text="🚨 Member01 sends Player Alpha to Member02", rosters=False, announcer=None
        )
    )

    assert exit_code == 1
    assert capsys.readouterr().out == "AIInvalidOutput\n"


MEMBERS = [MemberRef(1, "Member01", ("benny",)), MemberRef(2, "Member02", ())]


def _extract_deps(monkeypatch: pytest.MonkeyPatch, members=MEMBERS) -> None:
    deps = SimpleNamespace(settings=SimpleNamespace(sleeper_league_id="1"), conn=_ExplodingConn())
    monkeypatch.setattr(trades_cli, "build_deps", lambda: deps)
    monkeypatch.setattr(trades_cli, "build_ai", lambda _deps: None)
    monkeypatch.setattr(
        trades_cli, "SeasonRepository", lambda _conn: SimpleNamespace(current=lambda: 2026)
    )
    monkeypatch.setattr(
        trades_cli,
        "MemberAliasRepository",
        lambda _conn: SimpleNamespace(all_members=lambda: members),
    )
    monkeypatch.setattr(
        trades_cli, "PlayerRepository", lambda _conn: SimpleNamespace(all_active=list)
    )


def test_as_names_the_announcer_the_pipeline_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--as` is how a first-person announcement is rehearsed from the terminal:
    the listener places the sender from a handle, and a terminal has none."""
    _extract_deps(monkeypatch)
    seen = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return trades_cli.NOT_A_TRADE

    monkeypatch.setattr(trades_cli, "dry_run_pipeline", capture)

    exit_code = trades_cli.cmd_extract(
        argparse.Namespace(
            text="🚨 I sent Player Alpha to Member02", rosters=False, announcer="benny"
        )
    )

    assert exit_code == 0
    # Matched on an alias, the same spellings resolution accepts.
    assert seen["announcer"] == MEMBERS[0]


def test_extract_without_as_passes_no_announcer(monkeypatch: pytest.MonkeyPatch) -> None:
    _extract_deps(monkeypatch)
    seen = {}
    monkeypatch.setattr(
        trades_cli,
        "dry_run_pipeline",
        lambda *args, **kwargs: (seen.update(kwargs), trades_cli.NOT_A_TRADE)[1],
    )
    trades_cli.cmd_extract(
        argparse.Namespace(
            text="🚨 Member01 sends Player Alpha to Member02", rosters=False, announcer=None
        )
    )
    assert seen["announcer"] is None


def test_an_unknown_as_is_refused_rather_than_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silently dropping `--as` would print the answer for a chat with no handles
    loaded and look like the prompt failing to read the first person."""
    _extract_deps(monkeypatch)
    monkeypatch.setattr(trades_cli, "dry_run_pipeline", lambda *a, **k: pytest.fail("called"))

    exit_code = trades_cli.cmd_extract(
        argparse.Namespace(
            text="🚨 I sent Player Alpha to Member02", rosters=False, announcer="nobody-here"
        )
    )

    assert exit_code == 2
    assert capsys.readouterr().out == "no league member goes by nobody-here\n"


def test_find_member_matches_a_display_name_or_an_alias() -> None:
    assert trades_cli.find_member(MEMBERS, "member01") is MEMBERS[0]
    assert trades_cli.find_member(MEMBERS, "Benny") is MEMBERS[0]
    assert trades_cli.find_member(MEMBERS, "Member02") is MEMBERS[1]
    assert trades_cli.find_member(MEMBERS, "Member03") is None
