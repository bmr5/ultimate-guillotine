"""The league as an MCP server: the only door the agent has into the data.

Stdio transport, so Hermes launches it as a subprocess and talks JSON-RPC over
its pipes -- which is why nothing here may print to stdout. Every tool is one
of the functions in :mod:`~ultimate_guillotine.agent.tools.league`, wrapped
to return its dict as a JSON string; the descriptions are what the model reads
when it decides which to call, so they say what a tool answers and what its
arguments mean.
"""

import inspect
import json
import logging
import os
from collections.abc import Callable
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

from ultimate_guillotine.agent.tools import league
from ultimate_guillotine.agent.tools.source import DatabaseSource, FixtureSource, LeagueSource

log = logging.getLogger(__name__)

TOOL_NAMES = (
    "league_overview", "roster", "player", "projections", "trades", "price_history",
    "trade_math", "rules", "history", "survival", "transactions",
)
INSTRUCTIONS = (
    "Read-only data for the Ultimate Guillotine fantasy football league. Every snapshot-backed "
    "result carries as_of (when the data was synced), newest_sync and age_minutes; rules and "
    "history carry a source key instead. Members are named by their league label; resolve a "
    "member or player through a tool before reasoning about them. An 'error' key means the "
    "name did not resolve -- relay the message and ask, never guess."
)
FIXTURE_ENV = "UG_AGENT_FIXTURE"


def _dump(result: dict) -> str:
    return json.dumps(result, default=str, ensure_ascii=False)


def build_server(source: LeagueSource) -> tuple[MCPServer, dict[str, Callable[..., str]]]:
    """The server over one source, and its tools by name for tests and the dry run."""
    server = MCPServer("league", instructions=INSTRUCTIONS, log_level="WARNING")
    tools: dict[str, Callable[..., str]] = {}

    def register(fn: Callable[..., str]) -> Callable[..., str]:
        tools[fn.__name__] = fn
        # cleandoc, so the model reads a paragraph rather than the docstring's indentation.
        server.tool(name=fn.__name__, description=inspect.cleandoc(fn.__doc__ or ""))(fn)
        return fn

    @register
    def league_overview() -> str:
        """The season, the week, every team's label, FAAB, elimination, projected total,
        board rank (1 = lowest live projection, closest to the guillotine) and out starters.
        Call this first."""
        return _dump(league.league_overview(source))

    @register
    def roster(member: str, weeks_ahead: int = 0) -> str:
        """One member's roster: FAAB remaining, elimination, projected totals, and every
        player with position, NFL team, lineup slot, injury status and projected points.
        weeks_ahead (0-4) adds that many future weeks; projections are keyed by week number."""
        return _dump(league.roster(source, member, weeks_ahead))

    @register
    def player(name: str, weeks_ahead: int = 0) -> str:
        """One player: who holds them (holder is a member label, or 'free agent'), position,
        NFL team, injury status and projected points. weeks_ahead (0-4) adds that many future
        weeks; projections are keyed by week number, and are empty for a free agent because
        only rostered players are projected. An ambiguous name comes back as an error listing
        the matches."""
        return _dump(league.player(source, name, weeks_ahead))

    @register
    def projections(members: list[str] | None = None, scope: str = "starters") -> str:
        """This week's projected points: the named members side by side, or the whole
        league ranked when no members are given. scope 'starters' (the lineup) or 'roster'."""
        return _dump(league.projections(source, members or (), scope))

    @register
    def trades(season: int | None = None, member: str | None = None, limit: int = 25) -> str:
        """Registered trades for a season (default: this one), optionally only those a member
        was party to: code, week, kind, parties, assets and special terms."""
        return _dump(league.trades(source, season, member, limit))

    @register
    def price_history(position: str, kind: str = "permanent") -> str:
        """What the league has paid in FAAB at a position: the median and the biggest recent
        comparables. kind 'permanent', 'rental' or 'all'."""
        return _dump(league.price_history(source, position, kind))

    @register
    def trade_math(legs: list[dict[str, Any]], weeks_ahead: int = 0) -> str:
        """Value a proposed trade. legs: [{kind: player, player, from, to}, {kind: faab,
        amount, from, to}, {kind: term, text, from, to}]. Returns each side's lineup change,
        FAAB after, feasibility flags and each incoming player's points over replacement.
        weeks_ahead (0-4) sums the lineup change over this week and that many future weeks."""
        return _dump(league.trade_math(source, legs, weeks_ahead))

    @register
    def rules(topic: str | None = None) -> str:
        """The league's rules that bear on trades, waivers, the gulag and budgets; whole, or
        the section matching a topic."""
        return _dump(league.rules(source, topic))

    @register
    def history(season: int | None = None) -> str:
        """Past seasons: champion, runner-up, third, and the week-by-week eliminations; with
        a season, that season's catalogued trades too."""
        return _dump(league.history(source, season))

    @register
    def survival(week: int | None = None) -> str:
        """One week's scores lowest first (default: this week), who is eliminated and when,
        and how many are alive."""
        return _dump(league.survival(source, week))

    @register
    def transactions(week: int | None = None) -> str:
        """Sleeper's add/drop/waiver/trade transactions for a week (default: this one), by
        member and player name -- who just dropped or picked up whom."""
        return _dump(league.transactions(source, week))

    return server, tools


def serve(fixture: bool) -> int:
    """Run the server on stdio until Hermes closes the pipe."""
    if fixture or os.environ.get(FIXTURE_ENV) == "1":
        source: LeagueSource = FixtureSource()
    else:
        from ultimate_guillotine.config import load_settings
        from ultimate_guillotine.data.database import connect
        from ultimate_guillotine.sleeper.client import SleeperClient

        settings = load_settings()
        source = DatabaseSource(
            connect(settings), SleeperClient(httpx.Client()), settings.sleeper_league_id
        )
    server, _tools = build_server(source)
    server.run(transport="stdio")
    return 0
