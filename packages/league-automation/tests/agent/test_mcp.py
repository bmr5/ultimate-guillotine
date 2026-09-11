"""The tool server: every tool registered, every result JSON, nothing private in any of them."""

import asyncio
import json
import re
import subprocess
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

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


def test_a_tool_result_crosses_the_pipe_once() -> None:
    """No output schema, so mcp sends the JSON text once rather than also as structured_content."""
    server, _tools = build_server(FixtureSource())

    async def check() -> None:
        for tool in await server.list_tools():
            assert tool.output_schema is None, tool.name
            wire = tool.model_dump(by_alias=True, exclude_none=True)
            assert "outputSchema" not in wire, tool.name
        result = await server.call_tool("roster", {"member": "Member05"})
        assert result.structured_content is None
        assert json.loads(result.content[0].text)["member"] == "Member05"

    asyncio.run(check())


def test_the_enum_arguments_publish_their_choices_and_reject_a_typo() -> None:
    server, _tools = build_server(FixtureSource())

    async def check() -> None:
        schemas = {t.name: t.input_schema["properties"] for t in await server.list_tools()}
        assert schemas["projections"]["scope"]["enum"] == ["starters", "roster"]
        assert schemas["price_history"]["kind"]["enum"] == ["permanent", "rental", "all"]
        with pytest.raises(ToolError, match="'permanent', 'rental' or 'all'"):
            await server.call_tool("price_history", {"position": "RB", "kind": "bogus"})
        with pytest.raises(ToolError, match="'starters' or 'roster'"):
            await server.call_tool("projections", {"scope": "starter"})

    asyncio.run(check())


def test_descriptions_say_what_limit_and_the_trust_flags_mean() -> None:
    server, _tools = build_server(FixtureSource())
    described = {t.name: t.description for t in asyncio.run(server.list_tools())}
    assert "limit" in described["trades"]
    for flag in ("provisional", "coverage_pct", "projections_complete"):
        assert flag in described["league_overview"], flag


def test_ug_does_not_load_the_server_until_asked() -> None:
    """`ug` runs from cron all day; the mcp/httpx imports belong to `ug agent mcp` alone."""
    probe = (
        "import sys, ultimate_guillotine.cli.main; "
        "print('ultimate_guillotine.agent.tools.mcp' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
