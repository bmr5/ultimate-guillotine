"""Seasonal synchronization from Sleeper into ``public.members``/``public.teams``.

``sync_season`` never writes elimination state (weekly results, league
events, survival snapshots) -- it only reconciles the roster-of-record for
a season: members and their teams.
"""

from dataclasses import dataclass

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.models import SleeperLeague


@dataclass(frozen=True)
class SyncReport:
    members: int
    teams: int


def validate_league(league: SleeperLeague, expected_id: str, expected_rosters: int) -> None:
    """Raise ``ValueError`` if ``league`` doesn't match the expected season."""
    if league.league_id != expected_id:
        raise ValueError("league id mismatch")
    if league.total_rosters != expected_rosters:
        raise ValueError(f"expected {expected_rosters} rosters, got {league.total_rosters}")


def sync_season(
    client: SleeperClient,
    conn: psycopg.Connection,
    year: int,
    league_id: str,
) -> SyncReport:
    """Reconcile members and teams for ``year`` from Sleeper.

    Runs inside a single transaction; the caller is responsible for
    committing (or rolling back) the connection.
    """
    with conn.cursor() as cur:
        cur.execute("select id, expected_rosters from public.seasons where year = %s", (year,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"no season row for year {year}")
        season_id, expected_rosters = row

    league = client.get_league(league_id)
    validate_league(league, expected_id=league_id, expected_rosters=expected_rosters)

    users = client.get_users(league_id)
    rosters = client.get_rosters(league_id)
    users_by_id = {user.user_id: user for user in users}

    with conn.transaction(), conn.cursor() as cur:
        member_ids: dict[str, int] = {}
        for user in users:
            cur.execute(
                """
                    insert into public.members (display_name)
                    values (%s)
                    on conflict (display_name) do update set display_name = excluded.display_name
                    returning id
                    """,
                (user.display_name,),
            )
            member_row = cur.fetchone()
            if member_row is None:
                raise RuntimeError("insert returned no id")
            member_ids[user.user_id] = member_row[0]

        teams_synced = 0
        for roster in rosters:
            user = users_by_id.get(roster.owner_id)
            if user is None:
                continue
            member_id = member_ids[user.user_id]
            cur.execute(
                """
                    insert into public.teams
                        (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
                    values (%s, %s, %s, %s, %s)
                    on conflict (season_id, sleeper_roster_id) do update
                        set member_id = excluded.member_id,
                            sleeper_user_id = excluded.sleeper_user_id,
                            team_name = excluded.team_name
                    """,
                (season_id, member_id, user.user_id, roster.roster_id, user.team_name),
            )
            teams_synced += 1

    return SyncReport(members=len(member_ids), teams=teams_synced)
