"""What a ten-minute `ug sleeper sync` writes beyond members and teams.

The fake client, the roster payload, and the season/team id lookups come from
``tests/sleeper/conftest.py``.
"""

from decimal import Decimal

import pytest

from ultimate_guillotine.sleeper.models import SleeperUser
from ultimate_guillotine.sleeper.sync import sync_season

from .conftest import LEAGUE_ID, FakeClient


def _holdings_and_state(conn) -> tuple[list, list]:
    """Every roster-holding and team-state row, timestamps included."""
    with conn.cursor() as cur:
        cur.execute(
            "select season_id, team_id, sleeper_player_id, slot, slot_index, "
            "lineup_position, synced_at from public.roster_holdings order by id"
        )
        holdings = cur.fetchall()
        cur.execute(
            "select team_id, faab_used, wins, is_eliminated, eliminated_week, "
            "elimination_source, state_version, synced_at "
            "from public.team_season_state order by team_id"
        )
        return holdings, cur.fetchall()


def test_sync_caches_the_leagues_scoring_settings_on_the_season(conn, sleeper_client) -> None:
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select scoring_settings, roster_positions, waiver_budget, league_synced_at "
            "from public.seasons where year = 2026"
        )
        scoring, positions, budget, synced = cur.fetchone()
    assert scoring["rec"] == 1.0 and scoring["pass_yd"] == 0.04
    assert positions == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]
    assert budget == 1000 and synced is not None


def test_sync_writes_holdings_with_slots_and_lineup_positions(
    conn, sleeper_client, team_id
) -> None:
    report = sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    assert report.holdings > 0 and report.states == 18
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id, slot, slot_index, lineup_position "
            "from public.roster_holdings where team_id = %s order by sleeper_player_id",
            (team_id(1),),
        )
        rows = {row[0]: row[1:] for row in cur.fetchall()}
    assert rows["4034"] == ("starter", 0, "QB")
    assert rows["10881"] == ("ir", None, None)
    assert rows["4943"] == ("taxi", None, None)
    assert "0" not in rows


def test_a_dropped_player_disappears_from_holdings(conn, rosters, sleeper_client, team_id) -> None:
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    rosters[0]["players"] = [p for p in rosters[0]["players"] if p != "6794"]
    rosters[0]["starters"] = ["4034", "0", "0", "9488", "12517", "0", "7611", "12713", "SEA"]
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.roster_holdings "
            "where team_id = %s and sleeper_player_id = '6794'",
            (team_id(1),),
        )
        assert cur.fetchone()[0] == 0


def test_faab_record_and_points_land_in_team_season_state(conn, sleeper_client, team_id) -> None:
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select faab_budget, faab_used, faab_remaining, wins, losses, points_for, "
            "points_against from public.team_season_state where team_id = %s",
            (team_id(1),),
        )
        row = cur.fetchone()
    assert row == (1000, 250, 750, 2, 1, Decimal("312.45"), Decimal("289.07"))


def test_an_adjudicated_elimination_survives_a_sync_that_infers_otherwise(
    conn, sleeper_client, team_id
) -> None:
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    ruled_team = team_id(1)
    with conn.cursor() as cur:
        cur.execute(
            "update public.team_season_state set is_eliminated = true, eliminated_week = 2,"
            " elimination_source = 'adjudicator', state_version = 2 where team_id = %s",
            (ruled_team,),
        )
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select is_eliminated, eliminated_week, elimination_source, state_version "
            "from public.team_season_state where team_id = %s",
            (ruled_team,),
        )
        assert cur.fetchone() == (True, 2, "adjudicator", 2)


def test_a_tagged_roster_is_recorded_as_provisionally_eliminated(
    conn, sleeper_client, team_id
) -> None:
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select is_eliminated, eliminated_week, elimination_source, state_version "
            "from public.team_season_state where team_id = %s",
            (team_id(2),),
        )
        assert cur.fetchone() == (True, 3, "sleeper_inferred", 1)


def test_a_still_tagged_roster_keeps_the_week_it_was_eliminated_in(
    conn, sleeper_client, team_id
) -> None:
    """The tag stays on the roster all season; the elimination happened once.

    Week 5's sync re-infers the same `sleeper_inferred` elimination roster 2 was
    recorded with in week 3. Re-stamping `eliminated_week = 5` would rewrite
    league history, and bumping `state_version` for it would wake every consumer
    watching that counter, ten minutes at a time.
    """
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=5)
    with conn.cursor() as cur:
        cur.execute(
            "select is_eliminated, eliminated_week, elimination_source, state_version "
            "from public.team_season_state where team_id = %s",
            (team_id(2),),
        )
        assert cur.fetchone() == (True, 3, "sleeper_inferred", 1)


def test_a_newly_tagged_roster_bumps_the_state_version(
    conn, rosters, sleeper_client, team_id
) -> None:
    """Roster 1 syncs alive, then Ben tags it: that is the version-worthy change."""
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    rosters[0]["metadata"] = {"eliminated": "true"}
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=4)
    with conn.cursor() as cur:
        cur.execute(
            "select is_eliminated, eliminated_week, elimination_source, state_version "
            "from public.team_season_state where team_id = %s",
            (team_id(1),),
        )
        assert cur.fetchone() == (True, 4, "sleeper_inferred", 2)


def test_a_short_roster_payload_rolls_the_whole_pass_back(conn, rosters, sleeper_client) -> None:
    """The roster-count guard fires after everything is written, so it must undo it.

    A 17-roster answer is Sleeper mid-edit or a wrong league id. The pass raises,
    and holdings, team state and their `synced_at` stamps stay exactly as the last
    good sync left them.
    """
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    before = _holdings_and_state(conn)

    rosters.pop()
    with pytest.raises(ValueError, match="synced 17"):
        sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=4)

    assert _holdings_and_state(conn) == before


def test_sleeper_display_name_falls_back_to_the_username() -> None:
    """Sleeper occasionally returns an empty display_name, and then the username is
    the only label left. Whenever a display name exists it wins: the bare username is
    never what a consumer shows."""
    blank = SleeperUser(user_id="u", display_name="", username="ghostrider")
    assert blank.sleeper_display_name == "ghostrider"
    named = SleeperUser(user_id="u", display_name="Member01", username="member01_2019")
    assert named.sleeper_display_name == "Member01"


def test_sync_records_each_owners_sleeper_display_name(conn, sleeper_client) -> None:
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_display_name, nickname from public.members "
            "where display_name = 'Member01'"
        )
        assert cur.fetchone() == ("Member01", None)


def test_sync_never_clears_a_loaded_nickname(conn, sleeper_client) -> None:
    """`ug members aliases load` owns nickname. A sync refreshes the Sleeper label
    beside it and must leave the nickname exactly where it found it."""
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "update public.members set nickname = 'Big Ben' where display_name = 'Member01'"
        )
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select nickname, sleeper_display_name from public.members "
            "where display_name = 'Member01'"
        )
        assert cur.fetchone() == ("Big Ben", "Member01")


def test_repeated_syncs_produce_identical_rows(conn) -> None:
    client = FakeClient()
    sync_season(client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select season_id, team_id, sleeper_player_id, slot, slot_index, "
            "lineup_position from public.roster_holdings order by id"
        )
        first = cur.fetchall()
    sync_season(client, conn, 2026, LEAGUE_ID, week=3)
    with conn.cursor() as cur:
        cur.execute(
            "select season_id, team_id, sleeper_player_id, slot, slot_index, "
            "lineup_position from public.roster_holdings order by id"
        )
        assert cur.fetchall() == first
