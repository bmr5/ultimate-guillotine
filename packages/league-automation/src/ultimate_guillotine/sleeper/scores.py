"""Live team scores for one NFL week, from Sleeper's matchups feed.

Ben: "the team cards on the board should show their current score right next to
their projected. Also why does it show that it updated at 9:30PM it should always
be realtime!" There was no score sync at all -- the board's `Updated` stamp was
``team_week_projections.computed_at``, which only moves when a projection is
recomputed. This module is what writes ``public.team_week_scores``, and its
``synced_at`` is the stamp the board reads instead.

The feed is ``/league/{id}/matchups/{week}``: one object per roster, carrying
``points`` (the league's scoring already applied by Sleeper), ``custom_points``
(a commissioner override, null on every ordinary row), ``players_points`` (a map
over the *starters* -- nine entries for nine starters, the bench absent) and
``starters`` (the lineup, in slot order). The map and the lineup are both kept --
the map is unordered and says nothing about who started, and the lineup carries no
points -- so neither column can be derived from the other.

**Nothing here re-scores anything.** ``sleeper/scoring.py`` exists to score a
projection's raw stat line under the league's settings, because a projection feed
carries stats rather than points. A matchup row already carries the points Sleeper
itself put on the board, and recomputing them would produce a second number that
disagrees with what the league is looking at in the Sleeper app. Only the rounding
convention is shared: ``CENTS``, the same quantum every point total in this package
uses.

The write takes a connection and never opens a transaction of its own, matching
``projections.py``: ``ug sleeper scores`` fetches first and then upserts inside the
transaction ``run_scheduled`` already has open.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.scoring import CENTS
from ultimate_guillotine.sleeper.teams import teams_by_roster_id


@dataclass(frozen=True)
class TeamScore:
    """One team's live week, already mapped off Sleeper's roster id onto a team id."""

    team_id: int
    points: Decimal
    #: sleeper_player_id -> points, as the feed reports it: the starters only, not the bench.
    #: Floats, not Decimals: this goes into jsonb, and `json.dumps` cannot serialise a Decimal.
    #: Quantized to cents first, so the map and the total round the same way.
    players_points: dict[str, float]
    #: The lineup in the order Sleeper reports it. Empty-slot markers (`"0"`) are kept
    #: verbatim -- the position of a player in this list is his slot, so dropping the blanks
    #: would silently shift everyone after them into somebody else's slot.
    starters: list[str]


@dataclass(frozen=True)
class ScoreReport:
    """What one ``ug sleeper scores`` run wrote. Counts only, never a name."""

    teams: int
    week: int
    #: Matchup rows whose `roster_id` matches no team of this season. Zero on every ordinary
    #: run; anything else means `public.teams` is behind the league and needs `ug sleeper sync`.
    unmatched_rosters: int = 0


def _points(value: object) -> Decimal:
    """A matchup figure as cents, treating anything unusable as zero.

    Zero, not null: before kickoff Sleeper reports ``0`` and a team really has scored
    nothing, which is a fact rather than a gap. This is the one place the board's
    "render 0.0, never an em dash" rule is decided, and it is decided here rather than
    on the card so a missing key and a real zero cannot read differently.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return Decimal(0)
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def _matchup_points(record: dict[str, Any]) -> Decimal:
    """A team's total: ``custom_points`` when the commissioner has set one, else ``points``.

    Sleeper leaves ``custom_points`` null on every ordinary row and writes a manual correction
    into it when a commissioner overrides the auto-scoring -- a stat correction Sleeper never
    picked up, a keeper adjustment, a ruling. ``points`` keeps the auto-scored total the
    override replaced, so reading it there would put a number on the board that disagrees with
    what the league is looking at in the Sleeper app, for exactly the one team somebody had to
    correct by hand.

    An override that is not a usable number is treated as absent rather than as zero: unlike a
    missing ``points``, which really is "this team has not scored", a malformed override says
    nothing about the score, and blanking a real total over it would be the worse reading.
    """
    override = record.get("custom_points")
    if isinstance(override, (int, float)) and not isinstance(override, bool):
        return _points(override)
    return _points(record.get("points"))


def _players_points(value: object) -> dict[str, float]:
    """Sleeper's per-player map, keyed by string id, with non-numeric entries dropped.

    Whatever the feed puts in it is kept verbatim; in the live payload that is the starters
    alone, so a bench player has no entry here and the board leaves his live number blank.
    """
    if not isinstance(value, dict):
        return {}
    points: dict[str, float] = {}
    for player_id, raw in value.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        points[str(player_id)] = float(_points(raw))
    return points


def _starters(value: object) -> list[str]:
    """The lineup as reported, stringified. Order is the payload's; nothing is sorted."""
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value if entry is not None]


def load_team_scores(
    payload: list[dict[str, Any]], team_by_roster_id: dict[int, int]
) -> tuple[list[TeamScore], int]:
    """Parse the matchups payload into rows, and count what did not map to a team.

    A row whose ``roster_id`` names no team of this season is skipped rather than
    failing the run: that is `public.teams` lagging a league that has added a roster,
    which the next ``ug sleeper sync`` fixes, and it is no reason for the other
    seventeen teams to have no score on the board. The count comes back so the caller
    can say so.
    """
    rows: list[TeamScore] = []
    unmatched = 0
    for record in payload:
        if not isinstance(record, dict):
            continue
        roster_id = record.get("roster_id")
        if isinstance(roster_id, bool) or not isinstance(roster_id, int):
            continue
        team_id = team_by_roster_id.get(roster_id)
        if team_id is None:
            unmatched += 1
            continue
        rows.append(
            TeamScore(
                team_id=team_id,
                points=_matchup_points(record),
                players_points=_players_points(record.get("players_points")),
                starters=_starters(record.get("starters")),
            )
        )
    return rows, unmatched


class ScoreRepository:
    """Reads and writes for one week of live team scores.

    Every method runs on the caller's connection and inside the caller's transaction;
    none of them commit.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def teams_by_roster_id(self, season_id: int) -> dict[int, int]:
        """``sleeper_roster_id`` -> ``teams.id`` for one season; see ``sleeper/teams.py``."""
        return teams_by_roster_id(self._conn, season_id)

    def upsert_many(self, season_id: int, week: int, rows: list[TeamScore], now: datetime) -> int:
        """Write one row per team for the week, replacing the last run's numbers.

        Idempotent by the ``(season_id, team_id, week)`` unique key: this fires once a
        minute through a game window and has to rewrite the same eighteen rows rather
        than append to them. ``synced_at`` moves on every run, changed numbers or not --
        it is the answer to "how fresh is this?", and holding it back on an unchanged
        score would make a quiet Sunday afternoon read as a stalled sync.
        """
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.team_week_scores
                  (season_id, team_id, week, points, players_points, starters, synced_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, team_id, week) do update set
                  points = excluded.points,
                  players_points = excluded.players_points,
                  starters = excluded.starters,
                  synced_at = excluded.synced_at
                """,
                [
                    (
                        season_id,
                        row.team_id,
                        week,
                        row.points,
                        Jsonb(row.players_points),
                        row.starters,
                        now,
                    )
                    for row in rows
                ],
            )
        return len(rows)


def sync_scores(
    client: SleeperClient,
    conn: psycopg.Connection,
    league_id: str,
    season_id: int,
    week: int,
    now: datetime,
) -> ScoreReport:
    """Fetch one week of matchups and upsert a score row per team.

    **An empty feed refuses rather than writing zeros.** A 200 with no body, or a
    payload that maps to no team at all, would otherwise blank every live score on the
    board mid-game -- and a zero next to a projection reads as "they have scored
    nothing", not as "the feed is down". Same guard, and the same reasoning, as
    ``players.py`` refusing an empty directory.
    """
    payload = client.get_matchups(league_id, week)
    rows, unmatched = load_team_scores(payload, ScoreRepository(conn).teams_by_roster_id(season_id))
    if not rows:
        raise RuntimeError(f"sleeper returned no matchup rows for week {week}")
    ScoreRepository(conn).upsert_many(season_id, week, rows, now)
    return ScoreReport(teams=len(rows), week=week, unmatched_rosters=unmatched)
