"""One EOD snapshot: the reads, and the pure assembly that turns them into shapes.

The league itself -- rosters, lineup slots, this week's projections, coverage,
FAAB, elimination -- comes from the agent's
:class:`~ultimate_guillotine.agent.tools.snapshot.SnapshotRepository`, the package's one
six-query read of the data layer. This module joins it with what the summary
needs beyond that: each starter's NFL team and injury flag off the directory, the
week's scores and every earlier week's for the gulag replay, the Adjudicator's
gulag events when they exist, tonight's executed moves, and the one read outside
the data layer, Sleeper's public schedule.

**The reads and the assembly are separate on purpose.** :class:`EodRepository`
issues the SQL and :func:`assemble` is a pure function over plain rows, so the
assembly is tested over the fixture league with fabricated scores and the
repository is tested over the local database, and neither test has to stand in
for the other.

A schedule that cannot be read is carried as ``None``, never as an empty week:
with no schedule nobody can be called done, every fit starter stays
``remaining``, and the agent withholds the odds rather than computing them over
a guess.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import psycopg

from ultimate_guillotine.agent.tools.snapshot import LeagueSnapshot, SnapshotRepository
from ultimate_guillotine.history.archive_store import current_gulag_events
from ultimate_guillotine.sleeper.team_projections import TeamWeekRepository
from ultimate_guillotine.summary.lineup import build_starters
from ultimate_guillotine.summary.models import (
    LOCAL_TZ,
    EodSnapshot,
    Move,
    PlayerInfo,
    TeamLine,
)
from ultimate_guillotine.summary.phase import resolve_phase
from ultimate_guillotine.summary.schedule import Game, day_state, fetch_week_games, games_final


@dataclass(frozen=True)
class ScoreRow:
    """One ``team_week_scores`` row, as the assembly reads it."""

    team_id: int
    points: Decimal
    players_points: Mapping[str, float]
    starters: tuple[str, ...]
    synced_at: datetime


@dataclass(frozen=True)
class MoveRow:
    """One player moving one way in one executed transaction."""

    transaction_id: int
    kind: str
    occurred_at: datetime
    team_id: int
    sleeper_player_id: str
    action: str
    waiver_bid: int | None


@dataclass(frozen=True)
class EodInputs:
    """Everything :func:`assemble` needs, all plain values."""

    league: LeagueSnapshot
    players: Mapping[str, PlayerInfo]
    #: Names for players a move names who are on no roster -- the dropped ones.
    player_names: Mapping[str, str]
    scores: Sequence[ScoreRow]
    #: ``week -> team_id -> points`` for every week before this one.
    past_scores: Mapping[int, Mapping[int, Decimal]]
    events: Sequence[tuple[int | None, str, Mapping[str, object]]]
    moves: Sequence[MoveRow]
    #: ``None`` when the schedule could not be read; see the module docstring.
    week_games: Mapping[str, Game] | None
    starter_slots: int
    #: When the moves window opened; see :func:`moves_window_start`.
    moves_since: datetime | None = None


def local_midnight(now: datetime) -> datetime:
    """The UTC instant the league's current day began."""
    local = now.astimezone(LOCAL_TZ)
    return datetime.combine(local.date(), time.min, tzinfo=LOCAL_TZ).astimezone(UTC)


#: With no previous post on file the moves window is one day; after an outage it
#: is never more than this, so a week of claims is not replayed into one post.
MOVES_WINDOW_DEFAULT = timedelta(hours=24)
MOVES_WINDOW_MAX = timedelta(days=4)


def moves_window_start(now: datetime, previous_post_at: datetime | None) -> datetime:
    """When the moves section starts: the previous post, or a day back, capped.

    Ben's cadence skips Tuesdays and Saturdays, so "today" is the wrong window --
    the league wants everything that happened since it last heard from the bot.
    """
    if previous_post_at is None:
        return now - MOVES_WINDOW_DEFAULT
    return max(previous_post_at, now - MOVES_WINDOW_MAX)


def _moves(
    rows: Iterable[MoveRow], labels: Mapping[int, str], names: Mapping[str, str]
) -> tuple[Move, ...]:
    """The rows grouped per transaction and team, in the order they happened."""
    grouped: dict[tuple[datetime, int, int], dict] = {}
    for row in rows:
        key = (row.occurred_at, row.transaction_id, row.team_id)
        entry = grouped.setdefault(
            key, {"kind": row.kind, "bid": row.waiver_bid, "adds": [], "drops": []}
        )
        name = names.get(row.sleeper_player_id, row.sleeper_player_id)
        entry["adds" if row.action == "add" else "drops"].append(name)
    moves: list[Move] = []
    for (occurred_at, _transaction_id, team_id), entry in sorted(grouped.items()):
        moves.append(
            Move(
                kind=entry["kind"],
                occurred_at=occurred_at,
                team_label=labels.get(team_id, f"team {team_id}"),
                adds=tuple(entry["adds"]),
                drops=tuple(entry["drops"]),
                waiver_bid=entry["bid"],
            )
        )
    return tuple(moves)


def assemble(inputs: EodInputs) -> EodSnapshot:
    """The snapshot, from the reads. Pure: nothing here queries or fetches."""
    league = inputs.league
    available = inputs.week_games is not None
    week_games = inputs.week_games or {}
    scores = {row.team_id: row for row in inputs.scores}

    teams: list[TeamLine] = []
    for team in league.teams:
        score = scores.get(team.team_id)
        starters = build_starters(
            team.starters(),
            players=inputs.players,
            points=score.players_points if score is not None else {},
            week_games=week_games,
            schedule_available=available,
            starter_slots=inputs.starter_slots,
        )
        teams.append(
            TeamLine(
                team_id=team.team_id,
                member_id=team.member_id,
                label=team.member_label,
                team_name=team.team_name,
                faab_remaining=team.faab_remaining,
                is_eliminated=team.is_eliminated,
                eliminated_week=team.eliminated_week,
                points=score.points if score is not None else Decimal(0),
                starters=starters,
                scores_synced_at=score.synced_at if score is not None else None,
                has_score_row=score is not None,
            )
        )

    eliminated = {t.team_id: t.eliminated_week for t in league.teams if t.is_eliminated}
    phase = resolve_phase(
        league.week,
        inputs.events,
        inputs.past_scores,
        eliminated,
        [t.team_id for t in league.teams],
    )
    final, total = games_final(week_games) if available else (0, 0)
    names = {**league.player_names(), **inputs.player_names}
    labels = {t.team_id: t.label for t in teams}
    stamps = [row.synced_at for row in inputs.scores]
    return EodSnapshot(
        season=league.season,
        season_id=league.season_id,
        week=league.week,
        teams=tuple(teams),
        phase=phase,
        day_state=day_state(week_games) if available else "unknown",
        games_final=final,
        games_total=total,
        schedule_available=available,
        moves=_moves(inputs.moves, labels, names),
        data_synced_at=league.synced_at,
        scores_synced_at=max(stamps) if stamps else None,
        starter_slots=inputs.starter_slots,
        moves_since=inputs.moves_since,
    )


class EodRepository:
    """The reads beyond the league snapshot. Every method runs on the caller's
    connection and inside the caller's transaction; none of them commit."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def players(self, ids: Sequence[str]) -> dict[str, PlayerInfo]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, team, injury_status from public.players"
                " where sleeper_player_id = any(%s)",
                (list(ids),),
            )
            return {pid: PlayerInfo(team, status) for pid, team, status in cur.fetchall()}

    def player_names(self, ids: Sequence[str]) -> dict[str, str]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, full_name from public.players"
                " where sleeper_player_id = any(%s)",
                (list(ids),),
            )
            return dict(cur.fetchall())

    def week_scores(self, season_id: int, week: int) -> list[ScoreRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select team_id, points, players_points, starters, synced_at"
                " from public.team_week_scores where season_id = %s and week = %s"
                " order by team_id",
                (season_id, week),
            )
            return [
                ScoreRow(
                    team_id, points, dict(players_points or {}), tuple(starters or ()), synced_at
                )
                for team_id, points, players_points, starters, synced_at in cur.fetchall()
            ]

    def past_scores(self, season_id: int, before_week: int) -> dict[int, dict[int, Decimal]]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select week, team_id, points from public.team_week_scores"
                " where season_id = %s and week < %s order by week, team_id",
                (season_id, before_week),
            )
            past: dict[int, dict[int, Decimal]] = {}
            for week, team_id, points in cur.fetchall():
                past.setdefault(week, {})[team_id] = points
            return past

    def gulag_events(self, season_id: int) -> list[tuple[int | None, str, dict]]:
        archived = current_gulag_events(self._conn, season_id)
        if archived is not None:
            return archived
        with self._conn.cursor() as cur:
            cur.execute(
                "select week, event_type, payload from public.league_events"
                " where season_id = %s and event_type = 'gulag_entry' order by id",
                (season_id,),
            )
            return [(week, kind, dict(payload or {})) for week, kind, payload in cur.fetchall()]

    def moves_since(self, season_id: int, since: datetime) -> list[MoveRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select t.id, t.kind, t.occurred_at, m.team_id, m.sleeper_player_id, m.action,"
                " t.waiver_bid"
                " from public.transactions t"
                " join public.transaction_moves m on m.transaction_id = t.id"
                " where t.season_id = %s and t.occurred_at >= %s"
                " order by t.occurred_at, t.id, m.team_id, m.action",
                (season_id, since),
            )
            return [MoveRow(*row) for row in cur.fetchall()]

    def starter_slots(self, season_id: int) -> int:
        return TeamWeekRepository(self._conn).starter_slots(season_id)

    def previous_post_at(self, season_id: int) -> datetime | None:
        """When the league last got a post: the newest sent summary recap."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select max(created_at) from public.recaps"
                " where season_id = %s and recap_kind like 'eod:%%'"
                " and publication_state = 'sent'",
                (season_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def load_inputs(self, league: LeagueSnapshot, client, now: datetime) -> EodInputs:
        """Every read but the league itself, plus the one network call."""
        rostered = sorted({h.sleeper_player_id for t in league.teams for h in t.holdings})
        since = moves_window_start(now, self.previous_post_at(league.season_id))
        moves = self.moves_since(league.season_id, since)
        moved = sorted({m.sleeper_player_id for m in moves} - set(rostered))
        return EodInputs(
            league=league,
            players=self.players(rostered),
            player_names=self.player_names(moved) if moved else {},
            scores=self.week_scores(league.season_id, league.week),
            past_scores=self.past_scores(league.season_id, league.week),
            events=self.gulag_events(league.season_id),
            moves=moves,
            week_games=fetch_week_games(client, league.season, league.week),
            starter_slots=self.starter_slots(league.season_id),
            moves_since=since,
        )


def load_snapshot(conn: psycopg.Connection, client, now: datetime) -> EodSnapshot:
    """The whole snapshot: the league read, the joins, the schedule, assembled.

    Raises :class:`~ultimate_guillotine.agent.tools.snapshot.SnapshotUnavailable` when
    the data layer cannot say what week or league this is, exactly as the agent
    does; the caller words that for its own audience.
    """
    league = SnapshotRepository(conn).load()
    return assemble(EodRepository(conn).load_inputs(league, client, now))
