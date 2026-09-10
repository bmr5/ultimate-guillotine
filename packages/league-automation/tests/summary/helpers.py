"""Builders for the EOD shapes, so a test states only what it is about.

Every default is the quiet case -- a live team, no injuries, a settled week -- and
each builder takes keyword overrides for the one thing a test changes.
"""

from datetime import UTC, datetime
from decimal import Decimal

from ultimate_guillotine.summary.models import (
    EodSnapshot,
    Move,
    Phase,
    StarterLine,
    TeamLine,
)

NOW = datetime(2026, 9, 14, 4, 50, tzinfo=UTC)  # Sunday 11:50 PM Central


def starter(
    status: str = "done",
    *,
    position: str = "RB",
    projected: str | None = "12",
    points: str = "0",
    pid: str | None = "auto",
    name: str | None = None,
    injury: str | None = None,
    slot: str | None = None,
    nfl_team: str | None = "KC",
) -> StarterLine:
    player_id = None if status == "empty" else (f"p-{position}-{status}" if pid == "auto" else pid)
    return StarterLine(
        sleeper_player_id=player_id,
        name=name or (f"{position} {status}" if player_id else "empty slot"),
        position=None if status == "empty" else position,
        lineup_position=slot or (None if status == "empty" else position),
        nfl_team=None if status == "empty" else nfl_team,
        injury_status=injury,
        projected=None if projected is None else Decimal(projected),
        points=Decimal(points),
        status=status,
    )


def team(
    team_id: int,
    *,
    points: str = "0",
    starters: tuple[StarterLine, ...] = (),
    eliminated: bool = False,
    eliminated_week: int | None = None,
    label: str | None = None,
    faab: int = 100,
    has_score_row: bool = True,
) -> TeamLine:
    return TeamLine(
        team_id=team_id,
        member_id=team_id,
        label=label or f"Member{team_id:02d}",
        team_name=f"Team {team_id:02d}",
        faab_remaining=faab,
        is_eliminated=eliminated,
        eliminated_week=eliminated_week,
        points=Decimal(points),
        starters=starters,
        scores_synced_at=NOW,
        has_score_row=has_score_row,
    )


def done_team(team_id: int, points: str, **overrides) -> TeamLine:
    """A team whose whole week is over: one done starter, the score given."""
    return team(team_id, points=points, starters=(starter("done", points=points),), **overrides)


def phase(week: int = 1, kind: str = "entry", gulag: tuple[int, ...] = (),
          source: str = "none") -> Phase:
    return Phase(week=week, kind=kind, gulag_team_ids=gulag, gulag_source=source)


def snapshot(
    teams: tuple[TeamLine, ...],
    *,
    week: int = 1,
    phase_: Phase | None = None,
    day_state: str = "midweek",
    games_final: int = 13,
    games_total: int = 16,
    schedule_available: bool = True,
    moves: tuple[Move, ...] = (),
    starter_slots: int | None = None,
    moves_since: datetime | None = None,
) -> EodSnapshot:
    return EodSnapshot(
        season=2026,
        season_id=1,
        week=week,
        teams=teams,
        phase=phase_ or phase(week),
        day_state=day_state,
        games_final=games_final,
        games_total=games_total,
        schedule_available=schedule_available,
        moves=moves,
        data_synced_at=NOW,
        scores_synced_at=NOW,
        starter_slots=starter_slots if starter_slots is not None
        else max((len(t.starters) for t in teams), default=0),
        moves_since=moves_since,
    )
