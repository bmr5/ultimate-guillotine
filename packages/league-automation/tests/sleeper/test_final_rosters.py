"""Freezing the roster a team was eliminated with, exactly once.

Sleeper scatters an eliminated team's players -- the manager keeps dropping and
adding, or Ben clears the roster out -- so ``roster_holdings`` stops being the
answer to "who was on that team when it went out". ``public.final_rosters``
answers it, written by the first sync that observes the elimination and never
touched again.

The fake client, the mutable roster payload, and the season/team id lookups come
from ``tests/sleeper/conftest.py``.
"""

from ultimate_guillotine.sleeper.roster_state import Holding, holdings_payload
from ultimate_guillotine.sleeper.sync import sync_season

from .conftest import LEAGUE_ID


def snapshot(conn, team: int):
    """The one ``final_rosters`` row for a team, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "select eliminated_week, holdings, frozen_at from public.final_rosters "
            "where team_id = %s",
            (team,),
        )
        return cur.fetchone()


def test_holdings_payload_keeps_classification_order_and_every_slot_field() -> None:
    holdings = (
        Holding("4034", "starter", 0, "QB"),
        Holding("10881", "ir", None, None),
    )
    assert holdings_payload(holdings) == [
        {
            "sleeper_player_id": "4034",
            "slot": "starter",
            "slot_index": 0,
            "lineup_position": "QB",
        },
        {
            "sleeper_player_id": "10881",
            "slot": "ir",
            "slot_index": None,
            "lineup_position": None,
        },
    ]
    assert holdings_payload(()) == []


def test_an_elimination_freezes_that_teams_holdings(
    conn, rosters, sleeper_client, team_id
) -> None:
    # Two teams are out: roster 1 tagged here, roster 2 tagged in the fixture.
    rosters[0]["metadata"] = {"eliminated": "true"}
    report = sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    assert report.frozen == 2

    week, holdings, frozen_at = snapshot(conn, team_id(1))
    assert week == 3 and frozen_at is not None
    by_id = {h["sleeper_player_id"]: h for h in holdings}
    assert len(by_id) == 9
    assert by_id["4034"]["slot"] == "starter"
    assert by_id["4034"]["lineup_position"] == "QB"
    assert by_id["10881"]["slot"] == "ir"
    assert by_id["4943"]["slot"] == "taxi"
    assert "0" not in by_id


def test_a_later_sync_with_a_changed_roster_leaves_the_snapshot_alone(
    conn, rosters, sleeper_client, team_id
) -> None:
    rosters[0]["metadata"] = {"eliminated": "true"}
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    team = team_id(1)
    before = snapshot(conn, team)

    rosters[0]["players"] = ["4034", "99999"]
    rosters[0]["starters"] = ["4034", "0", "0", "0", "0", "0", "0", "0", "0"]
    rosters[0]["reserve"] = []
    rosters[0]["taxi"] = []
    report = sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=4)

    assert report.frozen == 0
    assert snapshot(conn, team) == before
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.final_rosters where team_id = %s", (team,))
        assert cur.fetchone()[0] == 1
    # roster_holdings still tracks Sleeper for an eliminated team; only the snapshot
    # is frozen, and consumers read the snapshot.
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_player_id from public.roster_holdings where team_id = %s "
            "order by sleeper_player_id",
            (team,),
        )
        assert [row[0] for row in cur.fetchall()] == ["4034", "99999"]


def test_an_adjudicated_elimination_freezes_without_any_sleeper_tag(
    conn, sleeper_client, team_id
) -> None:
    """The Adjudicator writes its ruling into team_season_state, not through the sync.
    The next sync observes it and takes the snapshot."""
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    team = team_id(1)
    assert snapshot(conn, team) is None

    with conn.cursor() as cur:
        cur.execute(
            "update public.team_season_state set is_eliminated = true, eliminated_week = 2, "
            "elimination_source = 'adjudicator' where team_id = %s",
            (team,),
        )
    report = sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)

    assert report.frozen == 1
    week, holdings, _ = snapshot(conn, team)
    assert week == 2 and len(holdings) == 9


def test_a_live_team_has_no_final_roster_row(conn, sleeper_client, team_id) -> None:
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    assert snapshot(conn, team_id(1)) is None
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.final_rosters")
        # Only roster 2, the one the fixture tags, is out.
        assert cur.fetchone()[0] == 1


def test_an_eliminated_team_with_an_empty_roster_freezes_an_empty_snapshot(
    conn, sleeper_client, team_id
) -> None:
    """Roster 2 is tagged eliminated and Sleeper reports no players at all. An empty
    array is the honest snapshot: it is what the team held when it went out, and
    refusing to freeze would leave the team unfrozen forever."""
    sync_season(sleeper_client, conn, 2026, LEAGUE_ID, week=3)
    week, holdings, frozen_at = snapshot(conn, team_id(2))
    assert week == 3 and holdings == [] and frozen_at is not None
