"""What `sleeper/scores.py` reads off a matchups payload, and what it writes.

The parsing cases are pure and need no database. The repository and `sync_scores`
cases run against the real table, because the whole value of the upsert is the
`(season_id, team_id, week)` conflict target -- a fake connection would assert the
SQL string this module happens to contain rather than the idempotence the every-
minute cron depends on.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ultimate_guillotine.sleeper.scores import (
    ScoreRepository,
    TeamScore,
    load_team_scores,
    sync_scores,
)

NOW = datetime(2026, 9, 13, 17, 30, tzinfo=UTC)

#: Two rosters, as Sleeper reports them mid-game: a total, a points map over the
#: *starters* only (the bench is on `players` and absent from `players_points`), and
#: the lineup in slot order with one slot still empty.
PAYLOAD = [
    {
        "roster_id": 901,
        "matchup_id": 1,
        "points": 87.32,
        "players_points": {"p1": 20.4, "p2": 12.0},
        "starters": ["p1", "p2", "0"],
        "players": ["p1", "p2", "bench1"],
    },
    {
        "roster_id": 902,
        "matchup_id": 1,
        "points": 0,
        "players_points": {"p3": 0},
        "starters": ["p3"],
        "players": ["p3"],
    },
]


class FakeMatchupClient:
    """Serves one matchups payload, and records what week was asked for."""

    def __init__(self, payload: list[dict] | None = None) -> None:
        self.payload = PAYLOAD if payload is None else payload
        self.calls: list[tuple[str, int]] = []

    def get_matchups(self, league_id: str, week: int) -> list[dict]:
        self.calls.append((league_id, week))
        return self.payload


def test_a_roster_id_is_mapped_onto_the_team_it_belongs_to() -> None:
    rows, unmatched = load_team_scores(PAYLOAD, {901: 11, 902: 22})
    assert [row.team_id for row in rows] == [11, 22]
    assert unmatched == 0


def test_points_are_cents_and_a_scoreless_team_is_zero_not_missing() -> None:
    """Before kickoff Sleeper reports 0, and a team really has scored nothing. The
    board renders `0.0` there rather than an em dash, and this is where that is decided."""
    rows, _unmatched = load_team_scores(PAYLOAD, {901: 11, 902: 22})
    assert rows[0].points == Decimal("87.32")
    assert rows[1].points == Decimal("0.00")


def test_a_missing_or_unusable_points_field_reads_as_zero() -> None:
    """Same reasoning: the absence of a number in this feed is a team that has not
    scored, never a gap to render as unknown."""
    payload = [{"roster_id": 901}, {"roster_id": 902, "points": "87.3"}]
    rows, _unmatched = load_team_scores(payload, {901: 11, 902: 22})
    assert [row.points for row in rows] == [Decimal(0), Decimal(0)]


def test_a_commissioner_override_wins_over_the_auto_scored_total() -> None:
    """`custom_points` is the number the league sees in the Sleeper app once somebody has
    corrected a row by hand; `points` still carries the auto-scored total it replaced."""
    payload = [{"roster_id": 901, "points": 87.32, "custom_points": 91.5}]
    rows, _unmatched = load_team_scores(payload, {901: 11})
    assert rows[0].points == Decimal("91.50")


def test_a_null_override_falls_back_to_the_auto_scored_total() -> None:
    """Which is every ordinary row: Sleeper sends the key with a null on rows nobody has
    touched, so an override read as "present" would blank the whole board."""
    payload = [
        {"roster_id": 901, "points": 87.32, "custom_points": None},
        {"roster_id": 902, "points": 12.0},
    ]
    rows, _unmatched = load_team_scores(payload, {901: 11, 902: 22})
    assert [row.points for row in rows] == [Decimal("87.32"), Decimal("12.00")]


def test_an_override_of_zero_is_an_override_not_an_absence() -> None:
    """A commissioner zeroing a team is a ruling, and `0` is not null."""
    payload = [{"roster_id": 901, "points": 87.32, "custom_points": 0}]
    rows, _unmatched = load_team_scores(payload, {901: 11})
    assert rows[0].points == Decimal("0.00")


def test_an_unusable_override_falls_back_rather_than_zeroing_a_real_total() -> None:
    """Unlike a missing `points`, a malformed override says nothing about the score, so
    the auto-scored total stands rather than being blanked over a bad field."""
    payload = [{"roster_id": 901, "points": 87.32, "custom_points": "91.5"}]
    rows, _unmatched = load_team_scores(payload, {901: 11})
    assert rows[0].points == Decimal("87.32")


def test_the_lineup_keeps_its_order_and_its_empty_slot_markers() -> None:
    """A player's position in `starters` is his slot, so dropping Sleeper's `"0"` blanks
    would shift everyone after them into somebody else's slot."""
    rows, _unmatched = load_team_scores(PAYLOAD, {901: 11})
    assert rows[0].starters == ["p1", "p2", "0"]


def test_the_points_map_is_copied_as_given_and_drops_non_numbers() -> None:
    """Whatever keys the feed puts in the map are kept -- it is never cross-referenced
    against `starters` -- but an entry that is not a number is no points at all."""
    payload = [
        {
            "roster_id": 901,
            "points": 1,
            "players_points": {"p1": 20.4, "p2": 3.5, "junk": None, "flag": True},
        }
    ]
    rows, _unmatched = load_team_scores(payload, {901: 11})
    assert rows[0].players_points == {"p1": 20.4, "p2": 3.5}


def test_a_roster_with_no_team_row_is_counted_not_fatal() -> None:
    """`public.teams` lagging a league that added a roster is a `ug sleeper sync` away
    from fixed, and no reason for the other teams to have no score on the board."""
    rows, unmatched = load_team_scores(PAYLOAD, {901: 11})
    assert [row.team_id for row in rows] == [11]
    assert unmatched == 1


def _seed(conn) -> tuple[int, int, int]:
    """One season and two teams, on the roster ids the payload above names.

    A member each: `public.teams` is unique on `(season_id, member_id)`, so one member
    cannot own both. The display names are the natural key sync upserts on and are never
    rendered anywhere; these two exist only to hang a team off.
    """
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        season_id = cur.fetchone()[0]
        team_ids = []
        for roster_id in (901, 902):
            cur.execute(
                "insert into public.members (display_name) values (%s) returning id",
                (f"score-fixture-{roster_id}",),
            )
            member_id = cur.fetchone()[0]
            cur.execute(
                "insert into public.teams (season_id, member_id, sleeper_user_id, "
                "sleeper_roster_id, team_name) values (%s, %s, %s, %s, 'T') returning id",
                (season_id, member_id, f"u{roster_id}", roster_id),
            )
            team_ids.append(cur.fetchone()[0])
    return season_id, team_ids[0], team_ids[1]


def test_the_roster_lookup_is_read_from_the_teams_table(conn) -> None:
    season_id, first, second = _seed(conn)
    assert ScoreRepository(conn).teams_by_roster_id(season_id) == {901: first, 902: second}


def test_a_sync_writes_one_row_per_team_with_the_payload_verbatim(conn) -> None:
    season_id, first, _second = _seed(conn)
    report = sync_scores(FakeMatchupClient(), conn, "league-1", season_id, 2, NOW)
    assert (report.teams, report.week, report.unmatched_rosters) == (2, 2, 0)
    with conn.cursor() as cur:
        cur.execute(
            "select points, players_points, starters, synced_at "
            "from public.team_week_scores where team_id = %s and week = 2",
            (first,),
        )
        points, players_points, starters, synced_at = cur.fetchone()
    assert points == Decimal("87.32")
    assert players_points == {"p1": 20.4, "p2": 12.0}
    assert starters == ["p1", "p2", "0"]
    assert synced_at == NOW


def test_a_second_sync_rewrites_the_row_and_moves_the_stamp(conn) -> None:
    """The job fires once a minute through a game window: it has to rewrite the same
    eighteen rows, and `synced_at` has to move even when the score has not, or a quiet
    afternoon reads on the board as a stalled sync."""
    season_id, first, _second = _seed(conn)
    sync_scores(FakeMatchupClient(), conn, "league-1", season_id, 2, NOW)
    later = NOW + timedelta(minutes=1)
    sync_scores(FakeMatchupClient(), conn, "league-1", season_id, 2, later)
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.team_week_scores where week = 2")
        assert cur.fetchone()[0] == 2
        cur.execute(
            "select synced_at from public.team_week_scores where team_id = %s and week = 2",
            (first,),
        )
        assert cur.fetchone()[0] == later


def test_a_changed_score_replaces_the_previous_number(conn) -> None:
    season_id, first, _second = _seed(conn)
    sync_scores(FakeMatchupClient(), conn, "league-1", season_id, 2, NOW)
    moved = [{**PAYLOAD[0], "points": 101.5, "players_points": {"p1": 34.6}}, PAYLOAD[1]]
    sync_scores(FakeMatchupClient(moved), conn, "league-1", season_id, 2, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select points, players_points from public.team_week_scores "
            "where team_id = %s and week = 2",
            (first,),
        )
        assert cur.fetchone() == (Decimal("101.50"), {"p1": 34.6})


def test_an_empty_feed_refuses_rather_than_zeroing_the_board(conn) -> None:
    """A 200 with no body must never blank every live score mid-game: a zero beside a
    projection reads as "they have scored nothing", not as "the feed is down"."""
    season_id, _first, _second = _seed(conn)
    with pytest.raises(RuntimeError, match="no matchup rows"):
        sync_scores(FakeMatchupClient([]), conn, "league-1", season_id, 2, NOW)
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.team_week_scores")
        assert cur.fetchone()[0] == 0


def test_a_payload_that_maps_to_no_team_at_all_refuses_too(conn) -> None:
    """Same guard from the other side: rows came back, but not one of them is a team of
    this season, so there is nothing to write and writing nothing quietly would look fine."""
    season_id, _first, _second = _seed(conn)
    stranger = [{"roster_id": 4242, "points": 90.0}]
    with pytest.raises(RuntimeError, match="no matchup rows"):
        sync_scores(FakeMatchupClient(stranger), conn, "league-1", season_id, 2, NOW)


def test_the_week_asked_of_sleeper_is_the_week_written(conn) -> None:
    season_id, _first, _second = _seed(conn)
    client = FakeMatchupClient()
    sync_scores(client, conn, "league-9", season_id, 7, NOW)
    assert client.calls == [("league-9", 7)]
    with conn.cursor() as cur:
        cur.execute("select distinct week from public.team_week_scores")
        assert cur.fetchall() == [(7,)]


def test_a_row_with_no_lineup_still_writes_the_empty_defaults(conn) -> None:
    season_id, first, _second = _seed(conn)
    bare = [{"roster_id": 901, "points": 0}]
    sync_scores(FakeMatchupClient(bare), conn, "league-1", season_id, 1, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select players_points, starters from public.team_week_scores where team_id = %s",
            (first,),
        )
        assert cur.fetchone() == ({}, [])


def test_the_upsert_returns_how_many_rows_it_wrote(conn) -> None:
    season_id, first, second = _seed(conn)
    rows = [
        TeamScore(first, Decimal("10.00"), {}, []),
        TeamScore(second, Decimal("20.00"), {}, []),
    ]
    assert ScoreRepository(conn).upsert_many(season_id, 3, rows, NOW) == 2
