"""Where the tools read the league from: the database, or the fixture league.

One protocol, two sources. ``DatabaseSource`` combines the shared league
snapshot with the reads the other tools need; ``FixtureSource``
answers every one of them from the closed-form league, so the whole agent --
Hermes session and all -- can be rehearsed against nothing real.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from ultimate_guillotine.agent.tools.fixture import fixture_snapshot
from ultimate_guillotine.agent.tools.names import PlayerInfo
from ultimate_guillotine.agent.tools.pricing import PriceRepository
from ultimate_guillotine.agent.tools.snapshot import LeagueSnapshot, SnapshotRepository
from ultimate_guillotine.data.repositories import MemberAliasRepository
from ultimate_guillotine.sleeper.players import PlayerRepository
from ultimate_guillotine.trades.context import league_rules
from ultimate_guillotine.trades.models import MemberRef


@dataclass(frozen=True)
class SeasonResult:
    season: int
    champion: str | None
    co_champion: str | None
    runner_up: str | None
    third: str | None
    team_count: int | None
    #: The season's week-by-week eliminations, member ids already replaced by labels.
    eliminations: list[dict[str, Any]]


@dataclass(frozen=True)
class WeekScore:
    member_label: str
    team_name: str
    week: int
    points: Decimal
    is_final: bool = False
    state_version: int = 1


@dataclass(frozen=True)
class GulagEntry:
    member_label: str
    week: int
    occurred_at: datetime


class LeagueSource(Protocol):
    def snapshot(self, horizon_weeks: int = 1) -> LeagueSnapshot: ...
    def members(self) -> list[MemberRef]: ...
    def players(self) -> dict[str, PlayerInfo]: ...
    def trades(self, seasons: Sequence[int]) -> list[dict]: ...
    def catalog(self, season: int) -> list[dict]: ...
    def season_results(self) -> list[SeasonResult]: ...
    def week_scores(self, week: int) -> list[WeekScore]: ...
    def gulag_entries(self, week: int) -> list[GulagEntry]: ...
    def survival_summary(self) -> dict | None: ...
    def transactions(self, week: int) -> list[dict]: ...
    def rules(self) -> str: ...


_LABEL = "coalesce(m.nickname, m.sleeper_display_name, m.display_name)"


class DatabaseSource:
    def __init__(self, conn, sleeper, league_id: str) -> None:
        self._conn = conn
        self._sleeper = sleeper
        self._league_id = league_id

    def snapshot(self, horizon_weeks: int = 1) -> LeagueSnapshot:
        return SnapshotRepository(self._conn).load(horizon_weeks=horizon_weeks)

    def members(self) -> list[MemberRef]:
        return MemberAliasRepository(self._conn).all_members()

    def players(self) -> dict[str, PlayerInfo]:
        return {
            p.sleeper_player_id: PlayerInfo(
                p.sleeper_player_id, p.full_name, p.position, p.team, p.injury_status
            )
            for p in PlayerRepository(self._conn).all_active()
        }

    def trades(self, seasons: Sequence[int]) -> list[dict]:
        return PriceRepository(self._conn).accepted_terms(seasons)

    def _labels(self) -> dict[int, str]:
        with self._conn.cursor() as cur:
            cur.execute(f"select m.id, {_LABEL} from public.members m")
            return {row[0]: row[1] for row in cur.fetchall()}

    def catalog(self, season: int) -> list[dict]:
        labels = self._labels()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select catalog_id, week, occurred_on, trade_type, structure, party_member_ids,
                       assets, faab_total, confidence
                from public.trade_catalog where season = %s order by week nulls last, id
                """,
                (season,),
            )
            return [
                {
                    "catalog_id": row[0], "week": row[1],
                    "occurred_on": row[2].isoformat() if row[2] else None,
                    "trade_type": row[3], "structure": row[4],
                    "parties": [labels.get(i, "former member") for i in (row[5] or [])],
                    "assets": row[6], "faab_total": row[7], "confidence": row[8],
                }
                for row in cur.fetchall()
            ]

    def season_results(self) -> list[SeasonResult]:
        labels = self._labels()

        def label(member_id) -> str | None:
            return None if member_id is None else labels.get(member_id, "former member")

        with self._conn.cursor() as cur:
            cur.execute(
                """
                select season, champion_member_id, co_champion_member_id, runner_up_member_id,
                       third_member_id, team_count, eliminations
                from public.season_results order by season
                """
            )
            results = []
            for row in cur.fetchall():
                entries = [
                    {**{k: v for k, v in entry.items() if k != "member_id"},
                     "member": label(entry.get("member_id"))}
                    for entry in (row[6] or [])
                ]
                results.append(SeasonResult(
                    row[0], label(row[1]), label(row[2]), label(row[3]), label(row[4]),
                    row[5], entries,
                ))
            return results

    def week_scores(self, week: int) -> list[WeekScore]:
        snapshot = self.snapshot()
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                select {_LABEL}, t.team_name, s.week, s.points, s.is_final, s.state_version
                from (
                    select distinct on (team_id) * from public.weekly_results
                    where season_id = %s and week = %s
                    order by team_id, state_version desc
                ) s
                join public.teams t on t.id = s.team_id
                join public.members m on m.id = t.member_id
                order by s.points asc
                """,
                (snapshot.season_id, week),
            )
            return [WeekScore(*row) for row in cur.fetchall()]

    def gulag_entries(self, week: int) -> list[GulagEntry]:
        season_id = self.snapshot().season_id
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                select {_LABEL}, e.week, e.occurred_at
                from public.league_events e
                join public.teams t on t.id::text = e.payload->>'team_id'
                    and t.season_id = e.season_id
                join public.members m on m.id = t.member_id
                where e.season_id = %s and e.week = %s and e.event_type = 'gulag_entry'
                order by e.occurred_at, e.id
                """, (season_id, week),
            )
            return [GulagEntry(*row) for row in cur.fetchall()]

    def survival_summary(self) -> dict | None:
        """Latest stored estimate, with its own week and public labels resolved afresh."""
        season_id = self.snapshot().season_id
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select week, snapshot_at, game_window, projection_source, model_version,
                       simulations, results
                from public.survival_snapshots where season_id = %s
                order by snapshot_at desc, id desc limit 1
                """, (season_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                f"select t.id, {_LABEL} from public.teams t "
                "join public.members m on m.id = t.member_id where t.season_id = %s",
                (season_id,),
            )
            labels = dict(cur.fetchall())
        teams = []
        for entry in row[6] if isinstance(row[6], list) else []:
            if not isinstance(entry, dict):
                continue
            teams.append({
                "member": labels.get(entry.get("team_id"), "former member"),
                "points": entry.get("points"),
                "projected_final": entry.get("projected_final"),
                "pending": entry.get("pending"),
                "adverse_event": entry.get("adverse_event"),
                "probability": entry.get("probability"),
                "is_estimated": entry.get("is_estimated"),
            })
        return {
            "week": row[0], "as_of": row[1].astimezone(UTC).isoformat(),
            "game_window": row[2], "projection_source": row[3], "model_version": row[4],
            "simulations": row[5], "teams": teams, "source": "public.survival_snapshots",
        }

    def transactions(self, week: int) -> list[dict]:
        return self._sleeper.get_transactions(self._league_id, week)

    def rules(self) -> str:
        return league_rules()


#: One injured bench player and one free agent, so the fixture exercises both.
FIXTURE_INJURED_ID = "p05b0"
FIXTURE_FREE_AGENT = PlayerInfo("fa1", "Free Agent One", "RB", "FIX", None)


class FixtureSource:
    """The closed-form league, answering every read the tools make."""

    def __init__(self, week: int = 6, **snapshot_kwargs) -> None:
        self._week = week
        self._kwargs = snapshot_kwargs

    def snapshot(self, horizon_weeks: int = 1) -> LeagueSnapshot:
        return fixture_snapshot(self._week, horizon_weeks=horizon_weeks, **self._kwargs)

    def members(self) -> list[MemberRef]:
        return [MemberRef(t.member_id, t.display_name, ()) for t in self.snapshot().teams]

    def players(self) -> dict[str, PlayerInfo]:
        pool = {
            h.sleeper_player_id: PlayerInfo(
                h.sleeper_player_id, h.player_name, h.position, "FIX",
                "Out" if h.sleeper_player_id == FIXTURE_INJURED_ID else None,
            )
            for t in self.snapshot().teams for h in t.holdings
        }
        pool[FIXTURE_FREE_AGENT.sleeper_player_id] = FIXTURE_FREE_AGENT
        return pool

    def trades(self, seasons: Sequence[int]) -> list[dict]:
        return []

    def catalog(self, season: int) -> list[dict]:
        return []

    def season_results(self) -> list[SeasonResult]:
        return [
            SeasonResult(2024, "Member03", None, "Member07", "Member11", 18, []),
            SeasonResult(2025, "Member09", None, "Member02", "Member14", 18,
                         [{"week": 2, "order": 1, "member": "Member17", "gulag_out": 1,
                           "pool_out": None, "remaining": 17, "note": None}]),
        ]

    def week_scores(self, week: int) -> list[WeekScore]:
        snapshot = self.snapshot()
        scores = [
            WeekScore(t.member_label, t.team_name, week,
                      (t.projected_now or Decimal(0)) - Decimal(1))
            for t in snapshot.teams
            if not t.is_eliminated or (t.eliminated_week is not None and t.eliminated_week >= week)
        ]
        return sorted(scores, key=lambda s: s.points)

    def gulag_entries(self, week: int) -> list[GulagEntry]:
        return []

    def survival_summary(self) -> dict | None:
        return None

    def transactions(self, week: int) -> list[dict]:
        return [{
            "type": "free_agent", "status": "complete", "leg": week,
            "created": int(datetime(2026, 10, 7, 15, 0, tzinfo=UTC).timestamp() * 1000),
            "roster_ids": [5], "adds": {"fa1": 5}, "drops": {"p05b5": 5}, "settings": None,
        }]

    def rules(self) -> str:
        return league_rules()
