"""The closed-form league on a Sunday night: what ``ug summary eod --fixture`` renders.

The agent's fixture league (:mod:`ultimate_guillotine.agent.tools.fixture`) supplies
the rosters, the projections and the eliminated team; this module adds the rest
of a week in progress, all closed-form so a reviewer can compute any line by
hand: an NFL team for every player, sixteen games of which thirteen are final,
scores for every starter whose game is over, one starter who is out and still in
his lineup, one flagged starter Sleeper has stopped projecting, one starter with
no projection and no flag, one empty slot, five weeks of past scores for the
gulag replay, and two moves from tonight.

Nothing here reads a file, a connection or the network, and every name in it is
``Member07`` and ``Starter 07-3``, so a rehearsal transcript carries nothing
about the league.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

from ultimate_guillotine.agent.tools.fixture import fixture_snapshot
from ultimate_guillotine.agent.tools.snapshot import LeagueHolding, LeagueSnapshot, LeagueTeamState
from ultimate_guillotine.summary.models import DayState, EodSnapshot, PlayerInfo
from ultimate_guillotine.summary.schedule import Game
from ultimate_guillotine.summary.snapshot import EodInputs, MoveRow, ScoreRow, assemble

FIXTURE_WEEK = 6
#: Sunday 11 October 2026, 11:50 PM Central.
FIXTURE_NOW = datetime(2026, 10, 12, 4, 50, tzinfo=UTC)

NFL_TEAMS = (
    "ARI",
    "ATL",
    "BAL",
    "BUF",
    "CAR",
    "CHI",
    "CIN",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GB",
    "HOU",
    "IND",
    "JAX",
    "KC",
    "LAC",
    "LAR",
    "LV",
    "MIA",
    "MIN",
    "NE",
    "NO",
    "NYG",
    "NYJ",
    "PHI",
    "PIT",
    "SEA",
    "SF",
    "TB",
    "TEN",
    "WAS",
)
#: Sixteen games, consecutive pairs of :data:`NFL_TEAMS`; the last three are Monday's.
GAMES = 16
MONDAY_GAMES = 3

#: (team number, starter slot) of the cases the message has to show.
OUT_STARTER = (9, 6)
DOUBTFUL_STARTER = (12, 3)
UNPROJECTED_STARTER = (14, 2)
EMPTY_SLOT_TEAM = 5
EMPTY_SLOT_INDEX = 7

_CENTS = Decimal("0.01")


def _nfl_team(team: int, slot_index: int) -> str:
    return NFL_TEAMS[(team + 7 * slot_index) % len(NFL_TEAMS)]


def _factor(team: int, slot_index: int) -> Decimal:
    """How a done starter did against his projection: 0.75 to 1.25, closed-form."""
    return Decimal("0.75") + Decimal("0.5") * Decimal((team * 7 + slot_index * 3) % 7) / 6


def _games(day_state: DayState) -> list[Game]:
    games: list[Game] = []
    for index in range(GAMES):
        monday = index >= GAMES - MONDAY_GAMES
        if day_state == "outlook":
            status = "pre_game"
        elif day_state == "final":
            status = "complete"
        else:
            status = "pre_game" if monday else "complete"
        games.append(
            Game(
                game_id=f"g{index:02d}",
                week=FIXTURE_WEEK,
                date=None,
                home=NFL_TEAMS[2 * index],
                away=NFL_TEAMS[2 * index + 1],
                status=status,
            )
        )
    return games


def _no_projection(holding: LeagueHolding) -> LeagueHolding:
    return replace(holding, projected_points=MappingProxyType({}))


def _tweaked(league: LeagueSnapshot) -> LeagueSnapshot:
    """The fixture league with the three lineup cases written into it."""
    teams: list[LeagueTeamState] = []
    for team in league.teams:
        number = team.member_id
        holdings: list[LeagueHolding] = []
        for holding in team.holdings:
            if holding.slot != "starter":
                holdings.append(holding)
                continue
            key = (number, holding.slot_index)
            if key == (EMPTY_SLOT_TEAM, EMPTY_SLOT_INDEX):
                continue
            if key in (DOUBTFUL_STARTER, UNPROJECTED_STARTER):
                holding = _no_projection(holding)
            holdings.append(holding)
        teams.append(replace(team, holdings=tuple(holdings)))
    return replace(league, teams=tuple(teams))


def _players(league: LeagueSnapshot) -> dict[str, PlayerInfo]:
    directory: dict[str, PlayerInfo] = {}
    for team in league.teams:
        for holding in team.holdings:
            slot = holding.slot_index if holding.slot_index is not None else 9
            injury = None
            if (team.member_id, holding.slot_index) == OUT_STARTER:
                injury = "Out"
            elif (team.member_id, holding.slot_index) == DOUBTFUL_STARTER:
                injury = "Questionable"
            directory[holding.sleeper_player_id] = PlayerInfo(
                _nfl_team(team.member_id, slot), injury
            )
    return directory


def _scores(
    league: LeagueSnapshot, games: dict[str, Game], players: dict[str, PlayerInfo]
) -> list[ScoreRow]:
    rows: list[ScoreRow] = []
    for team in league.teams:
        points: dict[str, float] = {}
        total = Decimal(0)
        for holding in team.starters():
            info = players[holding.sleeper_player_id]
            game = games.get(info.nfl_team or "")
            projected = holding.projected_now
            if game is None or game.status != "complete" or projected is None:
                continue
            if info.injury_status == "Out":
                continue
            scored = (projected * _factor(team.member_id, holding.slot_index or 0)).quantize(_CENTS)
            points[holding.sleeper_player_id] = float(scored)
            total += scored
        rows.append(
            ScoreRow(
                team_id=team.team_id,
                points=total,
                players_points=points,
                starters=tuple(h.sleeper_player_id for h in team.starters()),
                synced_at=FIXTURE_NOW,
            )
        )
    return rows


def _past_scores(league: LeagueSnapshot) -> dict[int, dict[int, Decimal]]:
    """Five weeks whose replay puts teams 16 and 18 in the week 6 gulag.

    Team 17 -- the eliminated one -- always scores high, so it never enters the
    replayed gulag; it went out by some other ruling, which is the case the
    replay has to survive.
    """
    return {
        week: {
            team.team_id: Decimal(250 if team.member_id == 17 else 200 - 5 * team.member_id + week)
            for team in league.teams
        }
        for week in range(1, FIXTURE_WEEK)
    }


def _moves(league: LeagueSnapshot) -> list[MoveRow]:
    by_number = {team.member_id: team for team in league.teams}
    waiver_at = FIXTURE_NOW - timedelta(hours=2)
    trade_at = FIXTURE_NOW - timedelta(hours=5)
    three, eight, eleven = by_number[3], by_number[8], by_number[11]
    return [
        MoveRow(
            1, "waiver", waiver_at, three.team_id, three.bench()[1].sleeper_player_id, "add", 12
        ),
        MoveRow(1, "waiver", waiver_at, three.team_id, "p-cut", "drop", 12),
        MoveRow(
            2, "trade", trade_at, eight.team_id, eleven.bench()[0].sleeper_player_id, "add", None
        ),
        MoveRow(
            2, "trade", trade_at, eleven.team_id, eleven.bench()[0].sleeper_player_id, "drop", None
        ),
        MoveRow(
            2, "trade", trade_at, eleven.team_id, eight.bench()[2].sleeper_player_id, "add", None
        ),
        MoveRow(
            2, "trade", trade_at, eight.team_id, eight.bench()[2].sleeper_player_id, "drop", None
        ),
    ]


def fixture_eod(*, day_state: DayState = "midweek", schedule_available: bool = True) -> EodSnapshot:
    """The league tonight, assembled through the same function production uses."""
    league = _tweaked(fixture_snapshot(week=FIXTURE_WEEK))
    games = {team: game for game in _games(day_state) for team in (game.home, game.away)}
    players = _players(league)
    return assemble(
        EodInputs(
            league=league,
            players=players,
            player_names={"p-cut": "Cut Player"},
            scores=_scores(league, games, players),
            past_scores=_past_scores(league),
            events=[],
            moves=_moves(league),
            week_games=games if schedule_available else None,
            starter_slots=8,
            moves_since=FIXTURE_NOW - timedelta(hours=24),
        )
    )
