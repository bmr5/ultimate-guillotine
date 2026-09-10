"""The one hop from Sleeper's roster ids to this data layer's team ids."""

import psycopg


def teams_by_roster_id(conn: psycopg.Connection, season_id: int) -> dict[int, int]:
    """``sleeper_roster_id`` -> ``teams.id`` for one season.

    Sleeper's feeds know rosters; every other table in this data layer knows teams.
    The hop is read from the database rather than from a league payload so a
    score, a pick, or a move can never be attached to a team the rest of the
    season's rows do not agree on. Runs on the caller's connection, inside the
    caller's transaction.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_roster_id, id from public.teams where season_id = %s",
            (season_id,),
        )
        return {roster_id: team_id for roster_id, team_id in cur.fetchall()}
