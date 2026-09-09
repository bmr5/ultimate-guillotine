import argparse
import subprocess
import sys

import pytest

from ultimate_guillotine.cli import trades as trades_cli


def test_trades_help_lists_commands() -> None:
    result = subprocess.run([sys.executable, "-m", "ultimate_guillotine.cli.main", "trades", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    for name in ("extract", "list", "retry", "replay"):
        assert name in result.stdout


def _trade(code: str = "T-2026-001") -> dict:
    return {
        "trade_id": 1, "trade_code": code, "status": "accepted", "revision": 1,
        "effective_week": 2,
        "terms": {"parties": [{"display_name": "Member01"}, {"display_name": "Member02"}]},
    }


def test_list_prints_a_header_over_the_rows(capsys: pytest.CaptureFixture[str]) -> None:
    trades_cli.print_trades([_trade()])
    assert capsys.readouterr().out == (
        "code  status  rev  week  parties\n"
        "T-2026-001  accepted  1  2  Member01, Member02\n"
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
