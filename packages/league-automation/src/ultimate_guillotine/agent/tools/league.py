"""The tool functions: what the agent may ask about the league, answered as plain data.

Every function takes a :class:`~ultimate_guillotine.agent.tools.source.LeagueSource`
and returns a JSON-able dict. Numbers are floats (two decimals in, two out),
names are public labels, and every result read off the snapshot carries
``as_of``, ``newest_sync`` and ``age_minutes`` so the agent can say how fresh
its answer is; ``rules`` and ``history`` read a file and finished seasons, and
carry no stamp. A name that does not resolve, or a league that cannot be read,
is an ``error`` key rather than an exception: the model reads the reason and
asks, rather than the tool call failing with nothing to relay.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from functools import wraps
from typing import Any

from ultimate_guillotine.advisor.pricing import (
    COMPARABLE_KINDS,
    comparables_for,
    median_faab,
    price_points,
)
from ultimate_guillotine.advisor.state import (
    AdvisorHolding,
    AdvisorTeamState,
    LeagueSnapshot,
    SnapshotUnavailable,
)
from ultimate_guillotine.agent.tools.math import (
    holdings_by_id,
    lineup_delta,
    replacement_levels,
    startable,
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


def _labels(snapshot: LeagueSnapshot) -> dict[int, str]:
    return {t.member_id: t.member_label for t in snapshot.teams}


def _positions(snapshot: LeagueSnapshot, source: LeagueSource) -> dict[str, str | None]:
    """Sleeper id to position for every player the league knows of."""
    return {
        p.sleeper_player_id: p.position
        for p in player_pool(snapshot, source.players()).values()
    }


def _asset(asset: dict, labels: dict[int, str], positions: dict[str, str | None]) -> dict:
    player_id = asset.get("player_id")
    return {
        "kind": asset.get("kind"),
        "player": asset.get("player_name"),
        "player_id": player_id,
        "position": positions.get(player_id) if player_id else None,
        "amount": asset.get("amount"),
        "unit": asset.get("unit"),
        "from": labels.get(asset.get("from_member_id"), "former member"),
        "to": labels.get(asset.get("to_member_id"), "former member"),
    }


@tool
def trades(
    source: LeagueSource,
    season: int | None = None,
    member: str | None = None,
    limit: int = 25,
    *,
    now: datetime | None = None,
) -> dict:
    snapshot = source.snapshot()
    labels = _labels(snapshot)
    positions = _positions(snapshot, source)
    wanted = None
    if member:
        wanted = resolve_member(member, snapshot, source.members()).member_id
    rendered = []
    for row in source.trades([season or snapshot.season]):
        terms = row.get("terms") or {}
        assets = terms.get("assets") or []
        parties = {a.get("from_member_id") for a in assets}
        parties |= {a.get("to_member_id") for a in assets}
        if wanted is not None and wanted not in parties:
            continue
        rendered.append({
            "code": row["trade_code"],
            "season": row["season"],
            "kind": terms.get("kind") or "permanent",
            "effective_week": terms.get("effective_week"),
            "parties": sorted(labels.get(p, "former member") for p in parties if p is not None),
            "assets": [_asset(a, labels, positions) for a in assets],
            "special_terms": list(terms.get("special_terms") or []),
        })
    return {
        "season": season or snapshot.season,
        "trades": rendered[:limit],
        **_stamp(snapshot, now),
    }


@tool
def price_history(
    source: LeagueSource, position: str, kind: str = "permanent", *, now: datetime | None = None
) -> dict:
    snapshot = source.snapshot()
    kinds = ("permanent", "rental", "payment") if kind == "all" else (kind,)
    if kinds == ("permanent",):
        kinds = COMPARABLE_KINDS
    rows = source.trades([snapshot.season, snapshot.season - 1])
    points = price_points(rows, _positions(snapshot, source))
    wanted = position.upper()
    return {
        "position": wanted,
        "kind": kind,
        "median_faab": median_faab(points, wanted, kinds=kinds),
        "comparables": [
            {
                "code": p.trade_code,
                "season": p.season,
                "kind": p.kind,
                "player": p.player_name,
                "faab": p.faab,
                "players_back": p.players_back,
            }
            for p in comparables_for(points, wanted, limit=5, kinds=kinds)
        ],
        **_stamp(snapshot, now),
    }


@tool
def trade_math(
    source: LeagueSource,
    legs: Sequence[dict],
    weeks_ahead: int = 0,
    *,
    now: datetime | None = None,
) -> dict:
    snapshot = source.snapshot(horizon_weeks=_horizon(weeks_ahead))
    refs = source.members()
    players = source.players()
    weeks = list(snapshot.weeks)
    holdings = holdings_by_id(snapshot)
    flags: list[str] = []
    sides: dict[int, dict[str, Any]] = {}

    def side(team: AdvisorTeamState) -> dict[str, Any]:
        if team.member_id not in sides:
            if team.is_eliminated:
                flags.append(f"{team.member_label} is eliminated and cannot trade")
            sides[team.member_id] = {
                "team": team, "incoming": [], "outgoing": [], "faab": team.faab_remaining,
                "receives": [], "sends": [],
            }
        return sides[team.member_id]

    for leg in legs:
        sender = resolve_member(str(leg.get("from", "")), snapshot, refs)
        receiver = resolve_member(str(leg.get("to", "")), snapshot, refs)
        giving, getting = side(sender), side(receiver)
        kind = leg.get("kind")
        if kind == "player":
            info = resolve_player(str(leg.get("player", "")), snapshot, players)
            held = holdings.get(info.sleeper_player_id)
            if held is None or held[0].member_id != sender.member_id:
                flags.append(f"{info.full_name} is not on {sender.member_label}'s roster")
                continue
            giving["outgoing"].append(held[1])
            getting["incoming"].append(held[1])
            giving["sends"].append(info.full_name)
            getting["receives"].append(info.full_name)
        elif kind in ("faab", "draft_dollars"):
            amount = int(leg.get("amount") or 0)
            faab = amount * 5 if kind == "draft_dollars" else amount
            if faab > sender.faab_remaining:
                flags.append(
                    f"{faab} FAAB is over {sender.member_label}'s budget of "
                    f"{sender.faab_remaining}"
                )
            giving["faab"] -= faab
            getting["faab"] += faab
            giving["sends"].append(f"{faab} FAAB")
            getting["receives"].append(f"{faab} FAAB")
        else:
            giving["sends"].append(str(leg.get("text") or kind))
            getting["receives"].append(str(leg.get("text") or kind))

    replacement = replacement_levels(snapshot)
    margins = {
        h.player_name: _points(h.projected_now - replacement[h.position])
        for s in sides.values() for h in s["incoming"]
        if h.position in replacement and h.projected_now is not None
    }
    return {
        "weeks": weeks,
        "projections_complete": snapshot.coverage_ok(),
        "flags": flags,
        "sides": {
            s["team"].member_label: {
                "receives": s["receives"],
                "sends": s["sends"],
                "faab_after": s["faab"],
                "lineup_delta": _points(
                    lineup_delta(startable(s["team"]), s["incoming"], s["outgoing"], weeks)
                ),
            }
            for s in sides.values()
        },
        "points_over_replacement": margins,
        "note": (
            "lineup_delta is the change to that side's best legal lineup, summed over weeks;"
            " null means a projection was missing. When projections_complete is false the"
            " league's totals are below the coverage gate and the delta is provisional."
        ),
        **_stamp(snapshot, now),
    }


@tool
def rules(source: LeagueSource, topic: str | None = None) -> dict:
    text = source.rules()
    if not topic:
        return {"rules": text}
    wanted = topic.casefold()
    sections = text.split("\n## ")
    kept = [s for s in sections[1:] if wanted in s.casefold()]
    return {"rules": "\n## ".join(["", *kept]).strip() if kept else text, "topic": topic}


@tool
def history(source: LeagueSource, season: int | None = None) -> dict:
    results = [r for r in source.season_results() if season is None or r.season == season]
    return {
        "seasons": [
            {
                "season": r.season,
                "champion": r.champion,
                "co_champion": r.co_champion,
                "runner_up": r.runner_up,
                "third": r.third,
                "team_count": r.team_count,
                "eliminations": r.eliminations,
                "catalogued_trades": source.catalog(r.season) if season is not None else [],
            }
            for r in results
        ],
    }


@tool
def survival(
    source: LeagueSource, week: int | None = None, *, now: datetime | None = None
) -> dict:
    snapshot = source.snapshot()
    wanted = week or snapshot.week
    return {
        "week": wanted,
        "scores": [
            {"member": s.member_label, "team_name": s.team_name, "points": _points(s.points)}
            for s in source.week_scores(wanted)
        ],
        "eliminated": [
            {"member": t.member_label, "week": t.eliminated_week, "source": t.elimination_source}
            for t in snapshot.teams if t.is_eliminated
        ],
        "alive": sum(1 for t in snapshot.teams if not t.is_eliminated),
        **_stamp(snapshot, now),
    }


@tool
def transactions(
    source: LeagueSource, week: int | None = None, *, now: datetime | None = None
) -> dict:
    snapshot = source.snapshot()
    wanted = week or snapshot.week
    by_roster = {t.sleeper_roster_id: t.member_label for t in snapshot.teams}
    names = {
        p.sleeper_player_id: p.full_name
        for p in player_pool(snapshot, source.players()).values()
    }
    rendered = []
    for raw in source.transactions(wanted):
        moves: dict[str, dict[str, list[str]]] = {}
        for field in ("adds", "drops"):
            for player_id, roster_id in (raw.get(field) or {}).items():
                member = by_roster.get(roster_id, f"roster {roster_id}")
                moves.setdefault(member, {"adds": [], "drops": []})[field].append(
                    names.get(player_id, player_id)
                )
        created = raw.get("created")
        rendered.append({
            "type": raw.get("type"),
            "status": raw.get("status"),
            "week": raw.get("leg") or wanted,
            "at": datetime.fromtimestamp(created / 1000, tz=UTC).isoformat() if created else None,
            "moves": [{"member": m, **v} for m, v in moves.items()],
            "waiver_bid": (raw.get("settings") or {}).get("waiver_bid"),
        })
    return {"week": wanted, "transactions": rendered, **_stamp(snapshot, now)}
