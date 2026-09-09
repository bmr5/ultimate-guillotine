"""Seasonal synchronization from Sleeper into the league's current-state tables.

One pass writes, in order: the league's cached settings on ``public.seasons``,
``public.members`` (the matching key and the Sleeper label beside it),
``public.teams``, then per team its ``public.roster_holdings`` and its
``public.team_season_state`` row. All of it in a single transaction, so the
board never reads a half-synced league.

The sync still decides nothing about elimination on its own: it merely carries a
roster tag forward as a *provisional* ``sleeper_inferred`` record, which the
Weekly Adjudicator's ruling always outranks. Weekly results, league events, and
survival snapshots stay out of here.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.models import SleeperLeague
from ultimate_guillotine.sleeper.roster_state import (
    RosterHoldingRepository,
    SeasonSettingsRepository,
    TeamStateRepository,
    bumps_state_version,
    classify_holdings,
    infer_elimination,
    merge_elimination,
    team_state_from_roster,
)


@dataclass(frozen=True)
class SyncReport:
    members: int
    teams: int
    holdings: int
    states: int


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
    week: int | None = None,
) -> SyncReport:
    """Reconcile the league's current state for ``year`` from Sleeper.

    ``week`` is the week an inferred elimination is stamped with -- the caller
    passes the NFL state's week, and ``None`` leaves ``eliminated_week`` null
    rather than guessing one from the calendar.

    Runs inside a single transaction; the caller is responsible for
    committing (or rolling back) the connection.
    """
    now = datetime.now(UTC)

    # Fetch from Sleeper before opening the transaction.
    league = client.get_league(league_id)
    users = client.get_users(league_id)
    rosters = client.get_rosters(league_id)
    users_by_id = {user.user_id: user for user in users}

    with conn.transaction(), conn.cursor() as cur:
        # Look up the season inside the transaction.
        cur.execute("select id, expected_rosters from public.seasons where year = %s", (year,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"no season row for year {year}")
        season_id, expected_rosters = row

        validate_league(league, expected_id=league_id, expected_rosters=expected_rosters)

        SeasonSettingsRepository(conn).cache(season_id, league, now)

        member_ids: dict[str, int] = {}
        for user in users:
            # nickname is deliberately absent from both the column list and the
            # update: `ug members aliases load` owns it, and a sync that listed it
            # would blank every nickname in the league every ten minutes.
            # sleeper_display_name holds Sleeper's display name verbatim, and null
            # when the account has none -- consumers fall back to teams.team_name.
            cur.execute(
                """
                    insert into public.members (display_name, sleeper_display_name)
                    values (%s, %s)
                    on conflict (display_name) do update set
                        display_name = excluded.display_name,
                        sleeper_display_name = excluded.sleeper_display_name
                    returning id
                    """,
                (user.display_name, user.display_name or None),
            )
            member_row = cur.fetchone()
            if member_row is None:
                raise RuntimeError("insert returned no id")
            member_ids[user.user_id] = member_row[0]

        holdings_repo = RosterHoldingRepository(conn)
        state_repo = TeamStateRepository(conn)
        teams_synced = 0
        holdings_written = 0
        states_written = 0
        for roster in rosters:
            user = users_by_id.get(roster.owner_id)
            if user is None:
                raise ValueError(f"roster {roster.roster_id} has no matching user")
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
                    returning id
                    """,
                (season_id, member_id, user.user_id, roster.roster_id, user.team_name),
            )
            team_row = cur.fetchone()
            if team_row is None:
                raise RuntimeError("team upsert returned no id")
            team_id = team_row[0]

            classification = classify_holdings(roster, league.roster_positions)
            holdings_written += holdings_repo.replace_for_team(
                season_id, team_id, classification.holdings, now
            )

            stored = state_repo.get_elimination(season_id, team_id)
            merged = merge_elimination(stored, infer_elimination(roster, week))
            state_repo.upsert(
                season_id,
                team_id,
                team_state_from_roster(roster, league.waiver_budget),
                merged,
                now,
                bumps_state_version(stored, merged),
            )
            states_written += 1
            teams_synced += 1

        if teams_synced != expected_rosters:
            raise ValueError(f"expected {expected_rosters} teams, synced {teams_synced}")

    return SyncReport(len(member_ids), teams_synced, holdings_written, states_written)
