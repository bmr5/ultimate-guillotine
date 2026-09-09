"""The NFL week, as one row every week-scoped job reads instead of the clock.

Deriving a week from the calendar is wrong twice a season (bye structure, a
pushed game) and wrong silently. This module makes the week a fact with a
timestamp: fresh enough and it is reused, stale and the caller refreshes it
inline rather than proceeding on a pinned week.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.sleeper.client import SleeperClient

#: Past this age the stored week is not trusted; a week-scoped job refreshes it first.
STATE_MAX_AGE = timedelta(minutes=60)


@dataclass(frozen=True)
class NflState:
    season: int
    season_type: str
    week: int
    display_week: int | None
    leg: int | None
    previous_season: int | None
    season_start_date: date | None
    raw: dict[str, object]
    synced_at: datetime


def _int_or_none(value: object) -> int | None:
    """Sleeper answers with ``"2026"``, not ``2026``, for every season field."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _date_or_none(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_nfl_state(raw: dict[str, object], now: datetime) -> NflState:
    """Turn Sleeper's state payload into typed values, or refuse it."""
    season = _int_or_none(raw.get("season"))
    week = _int_or_none(raw.get("week"))
    season_type = raw.get("season_type")
    if season is None:
        raise ValueError("sleeper state payload has no season")
    if week is None:
        raise ValueError("sleeper state payload has no week")
    if not isinstance(season_type, str) or not season_type:
        raise ValueError("sleeper state payload has no season_type")
    return NflState(
        season=season,
        season_type=season_type,
        week=week,
        display_week=_int_or_none(raw.get("display_week")),
        leg=_int_or_none(raw.get("leg")),
        previous_season=_int_or_none(raw.get("previous_season")),
        season_start_date=_date_or_none(raw.get("season_start_date")),
        raw=dict(raw),
        synced_at=now,
    )


class NflStateRepository:
    """Reads and writes the single `public.nfl_state` row (id = 1)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert(self, state: NflState) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.nfl_state
                  (id, season, season_type, week, display_week, leg, previous_season,
                   season_start_date, raw, synced_at)
                values (1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do update set
                  season = excluded.season,
                  season_type = excluded.season_type,
                  week = excluded.week,
                  display_week = excluded.display_week,
                  leg = excluded.leg,
                  previous_season = excluded.previous_season,
                  season_start_date = excluded.season_start_date,
                  raw = excluded.raw,
                  synced_at = excluded.synced_at
                """,
                (
                    state.season,
                    state.season_type,
                    state.week,
                    state.display_week,
                    state.leg,
                    state.previous_season,
                    state.season_start_date,
                    Jsonb(state.raw),
                    state.synced_at,
                ),
            )

    def get(self) -> NflState | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select season, season_type, week, display_week, leg, previous_season,
                       season_start_date, raw, synced_at
                from public.nfl_state where id = 1
                """
            )
            row = cur.fetchone()
        return NflState(*row) if row else None


def sync_nfl_state(client: SleeperClient, conn: psycopg.Connection, now: datetime) -> NflState:
    """Refresh the single state row. Fetch first, then one short transaction."""
    state = parse_nfl_state(client.get_nfl_state(), now)
    with conn.transaction():
        NflStateRepository(conn).upsert(state)
    return state


def current_week(client: SleeperClient, conn: psycopg.Connection, now: datetime) -> NflState:
    """The week to work on: the stored row when fresh, a fresh fetch otherwise.

    A stalled state job must never silently pin the league to last week, so
    staleness costs one extra Sleeper call rather than correctness.
    """
    stored = NflStateRepository(conn).get()
    if stored is not None and now - stored.synced_at <= STATE_MAX_AGE:
        return stored
    return sync_nfl_state(client, conn, now)
