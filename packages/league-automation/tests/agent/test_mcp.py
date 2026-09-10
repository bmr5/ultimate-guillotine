"""The tool server: every tool registered, every result JSON, nothing private in any of them."""

import json
import re

from ultimate_guillotine.agent.tools.mcp import TOOL_NAMES, build_server
from ultimate_guillotine.agent.tools.source import FixtureSource
from ultimate_guillotine.cli.main import build_parser

HASH = re.compile(r"\b[0-9a-f]{64}\b")


def test_every_tool_is_registered_and_answers_json() -> None:
    server, tools = build_server(FixtureSource())
    assert tuple(tools) == TOOL_NAMES == (
        "league_overview", "roster", "player", "projections", "trades", "price_history",
        "trade_math", "rules", "history", "survival", "transactions",
    )
    assert server.name == "league"
    overview = json.loads(tools["league_overview"]())
    assert overview["week"] == 6 and len(overview["teams"]) == 18
    assert json.loads(tools["roster"]("Member05"))["member"] == "Member05"
    assert json.loads(tools["player"]("Starter 07-3"))["holder"] == "Member07"
    assert len(json.loads(tools["projections"]())["rows"]) == 17
    assert json.loads(tools["rules"]("trading"))["topic"] == "trading"
    assert json.loads(tools["history"]())["seasons"][0]["season"] == 2024
    assert json.loads(tools["survival"]())["week"] == 6
    assert json.loads(tools["transactions"]())["transactions"][0]["type"] == "free_agent"
    assert json.loads(tools["trades"]())["trades"] == []
    assert json.loads(tools["price_history"]("RB"))["comparables"] == []
    math = json.loads(tools["trade_math"]([
        {"kind": "player", "player": "Bench 02-0", "from": "Member02", "to": "Member18"},
    ]))
    assert "Member18" in math["sides"]


def test_no_tool_result_carries_a_join_key_a_hash_or_a_handle() -> None:
    _server, tools = build_server(FixtureSource())
    calls = {
        "league_overview": (), "roster": ("Member05",), "player": ("Bench 05-0",),
        "projections": (), "trades": (), "price_history": ("RB",), "rules": (),
        "history": (), "survival": (), "transactions": (),
        "trade_math": ([{"kind": "faab", "amount": 5, "from": "Member02", "to": "Member03"}],),
    }
    for name, args in calls.items():
        text = tools[name](*args)
        assert "display_name" not in text, name
        assert not HASH.search(text), name
        assert "+1555" not in text and "iMessage;" not in text, name


def test_an_error_is_an_answer_not_an_exception() -> None:
    _server, tools = build_server(FixtureSource())
    assert "No match" in json.loads(tools["roster"]("Nobody"))["error"]


def test_the_cli_knows_the_server() -> None:
    args = build_parser().parse_args(["agent", "mcp", "--fixture"])
    assert args.group == "agent" and args.command == "mcp" and args.fixture is True
