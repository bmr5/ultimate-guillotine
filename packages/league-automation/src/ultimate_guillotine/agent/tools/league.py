"""The tool functions: what the agent may ask about the league, answered as plain data.

Every function takes a :class:`~ultimate_guillotine.agent.tools.source.LeagueSource`
and returns a JSON-able dict. Numbers are floats (two decimals in, two out),
names are public labels, and every result carries ``as_of``, ``newest_sync``
and ``age_minutes`` so the agent can say how fresh its answer is. A name that does
not resolve, or a league that cannot be read, is an ``error`` key rather than
an exception: the model reads the reason and asks, rather than the tool call
failing with nothing to relay.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from typing import Any

from ultimate_guillotine.advisor.state import (
    AdvisorHolding,
    AdvisorTeamState,
    LeagueSnapshot,
    SnapshotUnavailable,
)
from ultimate_guillotine.agent.tools.names import (
    Ambiguous,
    PlayerInfo,
    Unknown,
    player_pool,
    resolve_member,
    resolve_player,
)
from ultimate_guillotine.agent.tools.source import LeagueSource

#: Sleeper statuses that take a starter out of a lineup. The rest tag a player.
OUT_STATUSES = frozenset({"Out", "IR", "PUP", "Sus", "COV", "DNR"})
MAX_WEEKS_AHEAD = 4


def tool(fn: Callable[..., dict]) -> Callable[..., dict]:
    """Turn a name or data failure into an ``error`` the agent can read."""

    @wraps(fn)
    def call(*args, **kwargs) -> dict:
        try:
            return fn(*args, **kwargs)
        except (Unknown, Ambiguous, SnapshotUnavailable) as exc:
            return {"error": str(exc)}

    return call


def _points(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _stamp(snapshot: LeagueSnapshot, now: datetime | None) -> dict[str, Any]:
    """How fresh a result is, dated from the stamp its age is measured on.

    A snapshot is stitched from several syncs. ``as_of`` is the *oldest* of
    their stamps -- the one :meth:`LeagueSnapshot.age` counts from, so the date
    and ``age_minutes`` agree -- and ``newest_sync`` the newest, so the agent
    can see the spread between them. Both are rendered in UTC.
    """
    moment = now or datetime.now(UTC)
    return {
        "as_of": snapshot.oldest_synced_at.astimezone(UTC).isoformat(),
        "newest_sync": snapshot.synced_at.astimezone(UTC).isoformat(),
        "age_minutes": max(0, int(snapshot.age(moment).total_seconds() // 60)),
    }


def _board(snapshot: LeagueSnapshot) -> dict[int, int]:
    """Member id to board rank, 1 being the lowest live projection: the guillotine's order."""
    live = [t for t in snapshot.teams if not t.is_eliminated and t.projected_now is not None]
    ordered = sorted(live, key=lambda t: (t.projected_now, t.member_id))
    return {team.member_id: index + 1 for index, team in enumerate(ordered)}


def _out_starters(team: AdvisorTeamState, players: dict[str, PlayerInfo]) -> list[str]:
    return [
        h.player_name for h in team.starters()
        if (p := players.get(h.sleeper_player_id)) and p.injury_status in OUT_STATUSES
    ]


def _holding(
    holding: AdvisorHolding, players: dict[str, PlayerInfo], weeks: Sequence[int]
) -> dict[str, Any]:
    info = players.get(holding.sleeper_player_id)
    return {
        "player_id": holding.sleeper_player_id,
        "name": holding.player_name,
        "position": holding.position,
        "nfl_team": info.team if info else None,
        "slot": holding.slot,
        "lineup_position": holding.lineup_position,
        "injury_status": info.injury_status if info else None,
        "projections": {w: _points(holding.projected_for(w)) for w in weeks},
    }


def _horizon(weeks_ahead: int) -> int:
    return 1 + max(0, min(int(weeks_ahead), MAX_WEEKS_AHEAD))


@tool
def league_overview(source: LeagueSource, *, now: datetime | None = None) -> dict:
    snapshot = source.snapshot()
    players = player_pool(snapshot, source.players())
    board = _board(snapshot)
    teams = [
        {
            "member": t.member_label,
            "team_name": t.team_name,
            "faab_remaining": t.faab_remaining,
            "eliminated": t.is_eliminated,
            "eliminated_week": t.eliminated_week,
            "projected": _points(t.projected_now),
            "coverage_pct": _points(t.coverage_pct),
            "provisional": t.is_provisional,
            "board_rank": board.get(t.member_id),
            "out_starters": _out_starters(t, players),
        }
        for t in snapshot.teams
    ]
    alive = [t for t in teams if not t["eliminated"]]
    return {
        "season": snapshot.season,
        "week": snapshot.week,
        "teams_alive": len(alive),
        "projections_complete": snapshot.coverage_ok(),
        "teams": teams,
        "note": (
            "board_rank 1 is the lowest live projection: the two lowest each week enter the "
            "gulag. Projections are Sleeper's, scored with the league's own settings."
        ),
        **_stamp(snapshot, now),
    }


@tool
def roster(
    source: LeagueSource, member: str, weeks_ahead: int = 0, *, now: datetime | None = None
) -> dict:
    snapshot = source.snapshot(horizon_weeks=_horizon(weeks_ahead))
    team = resolve_member(member, snapshot, source.members())
    players = player_pool(snapshot, source.players())
    weeks = list(snapshot.weeks)
    return {
        "member": team.member_label,
        "team_name": team.team_name,
        "faab_remaining": team.faab_remaining,
        "eliminated": team.is_eliminated,
        "weeks": weeks,
        "projected": {w: _points(team.projected_for(w)) for w in weeks},
        "holdings": [_holding(h, players, weeks) for h in team.holdings],
        **_stamp(snapshot, now),
    }


@tool
def player(
    source: LeagueSource, name: str, weeks_ahead: int = 0, *, now: datetime | None = None
) -> dict:
    snapshot = source.snapshot(horizon_weeks=_horizon(weeks_ahead))
    info = resolve_player(name, snapshot, source.players())
    weeks = list(snapshot.weeks)
    for team in snapshot.teams:
        for holding in team.holdings:
            if holding.sleeper_player_id == info.sleeper_player_id:
                return {
                    "holder": team.member_label,
                    "holder_eliminated": team.is_eliminated,
                    **_holding(holding, {info.sleeper_player_id: info}, weeks),
                    **_stamp(snapshot, now),
                }
    return {
        "holder": "free agent",
        "player_id": info.sleeper_player_id,
        "name": info.full_name,
        "position": info.position,
        "nfl_team": info.team,
        "slot": None,
        "injury_status": info.injury_status,
        "projections": {},
        **_stamp(snapshot, now),
    }


@tool
def projections(
    source: LeagueSource,
    members: Sequence[str] = (),
    scope: str = "starters",
    *,
    now: datetime | None = None,
) -> dict:
    snapshot = source.snapshot()
    refs = source.members()
    board = _board(snapshot)
    if members:
        teams = [resolve_member(m, snapshot, refs) for m in members]
    else:
        teams = sorted(
            (t for t in snapshot.teams if not t.is_eliminated),
            key=lambda t: (t.projected_now is None, -(t.projected_now or Decimal(0))),
        )

    def projected(team: AdvisorTeamState) -> float | None:
        if scope == "roster":
            points = [h.projected_now for h in team.holdings if h.projected_now is not None]
            return _points(sum(points, Decimal(0))) if points else None
        return _points(team.projected_now)

    return {
        "week": snapshot.week,
        "scope": "roster" if scope == "roster" else "starters",
        "rows": [
            {
                "member": t.member_label,
                "team_name": t.team_name,
                "projected": projected(t),
                "board_rank": board.get(t.member_id),
                "eliminated": t.is_eliminated,
                "provisional": t.is_provisional,
            }
            for t in teams
        ],
        **_stamp(snapshot, now),
    }
