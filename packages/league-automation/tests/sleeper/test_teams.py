"""The one hop from Sleeper's roster ids to this data layer's team ids, read from the
table rather than from the league payload so every sync attaches rows to the same team."""

from ultimate_guillotine.sleeper.teams import teams_by_roster_id


def test_the_hop_is_read_from_the_teams_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        season_id = cur.fetchone()[0]
        cur.execute("insert into public.members (display_name) values ('hop-fixture') returning id")
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values (%s, %s, 'u-hop', 907, 'T') returning id",
            (season_id, member_id),
        )
        team_id = cur.fetchone()[0]
    assert teams_by_roster_id(conn, season_id) == {907: team_id}


def test_a_season_with_no_teams_is_an_empty_map(conn) -> None:
    assert teams_by_roster_id(conn, -1) == {}
