"""Building one EOD snapshot: the pure assembly, and the reads that feed it.

The assembly cases run over the Advisor's closed-form league with fabricated
scores, a half-played schedule and a few injuries; the repository cases run the
same reads against the local database over ``db_seed``.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.advisor.fixture import fixture_snapshot
from tests.summary import db_seed
from ultimate_guillotine.summary.models import PlayerInfo
from ultimate_guillotine.summary.schedule import Game
from ultimate_guillotine.summary.snapshot import (
    EodInputs,
    EodRepository,
    MoveRow,
    ScoreRow,
    assemble,
    load_snapshot,
    local_midnight,
    moves_window_start,
)

WEEK = 6
NOW = datetime(2026, 10, 12, 4, 50, tzinfo=UTC)  # Sunday 11:50 PM Central


def _game(game_id: str, home: str, away: str, status: str) -> Game:
    return Game(game_id=game_id, week=WEEK, date=None, home=home, away=away, status=status)


#: PHI/DAL are done, KC/DEN still to come, SF/SEA under way.
GAMES = {
    team: game
    for game in (
        _game("g1", "PHI", "DAL", "complete"),
        _game("g2", "KC", "DEN", "pre_game"),
        _game("g3", "SF", "SEA", "in_game"),
    )
    for team in (game.home, game.away)
}


def _inputs(*, games=GAMES, scores=None, events=(), moves=(), players=None) -> EodInputs:
    league = fixture_snapshot(week=WEEK)
    # Team 1's starters play for PHI (done), team 2's for KC (to come), team 3's for SF
    # (live), everyone else's for NYJ, who have no game this week.
    nfl_team = {101: "PHI", 102: "KC", 103: "SF"}
    directory = {
        h.sleeper_player_id: PlayerInfo(nfl_team.get(t.team_id, "NYJ"), None)
        for t in league.teams
        for h in t.holdings
    }
    if players:
        directory.update(players)
    if scores is None:
        scores = [
            ScoreRow(
                t.team_id,
                Decimal(100 + t.team_id),
                {h.sleeper_player_id: 11.5 for h in t.starters()[:2]},
                tuple(h.sleeper_player_id for h in t.starters()),
                NOW,
            )
            for t in league.teams
            if t.team_id != 103
        ]
    return EodInputs(
        league=league,
        players=directory,
        player_names={"p-gone": "Gone Player"},
        scores=scores,
        past_scores={
            w: {t.team_id: Decimal(80 + t.team_id) for t in league.teams} for w in range(1, WEEK)
        },
        events=list(events),
        moves=list(moves),
        week_games=games,
        starter_slots=8,
        moves_since=NOW - timedelta(hours=24),
    )


def test_every_team_becomes_a_line_with_the_fixture_s_labels() -> None:
    snap = assemble(_inputs())
    assert len(snap.teams) == 18
    assert snap.season == 2026 and snap.week == WEEK
    assert snap.team(101).label == "Member01"
    assert snap.team(117).is_eliminated
    assert snap.starter_slots == 8
    assert snap.data_synced_at == fixture_snapshot(week=WEEK).synced_at


def test_starter_statuses_follow_each_player_s_game() -> None:
    snap = assemble(_inputs())
    assert {s.status for s in snap.team(101).starters} == {"done"}
    assert {s.status for s in snap.team(102).starters} == {"remaining"}
    assert {s.status for s in snap.team(103).starters} == {"live"}
    assert {s.status for s in snap.team(104).starters} == {"bye"}


def test_points_come_off_the_score_row_and_a_missing_row_is_an_absence() -> None:
    snap = assemble(_inputs())
    team = snap.team(101)
    assert team.points == Decimal(201)
    assert team.has_score_row
    assert [s.points for s in team.starters][:3] == [Decimal("11.50"), Decimal("11.50"), Decimal(0)]
    missing = snap.team(103)
    assert not missing.has_score_row
    assert missing.points == Decimal(0)
    assert snap.scores_synced_at == NOW


def test_an_injury_flag_from_the_directory_takes_a_starter_out() -> None:
    league = fixture_snapshot(week=WEEK)
    first = league.teams[0].starters()[0].sleeper_player_id
    snap = assemble(_inputs(players={first: PlayerInfo("PHI", "Out")}))
    starter = snap.team(101).starters[0]
    assert starter.status == "out"
    assert starter.injury_status == "Out"


def test_the_phase_is_resolved_from_the_events_and_the_past_scores() -> None:
    events = [(WEEK, "gulag_entry", {"team_id": 105}), (WEEK, "gulag_entry", {"team_id": 106})]
    snap = assemble(_inputs(events=events))
    assert (snap.phase.kind, snap.phase.gulag_team_ids, snap.phase.gulag_source) == (
        "gulag",
        (105, 106),
        "events",
    )
    replayed = assemble(_inputs())
    assert replayed.phase.gulag_source == "replay"
    # Team 17 is out (week 5 in the fixture), so the week 6 gulag is replayed from the
    # week 5 scores of everyone alive then, less the week 5 gulag.
    assert len(replayed.phase.gulag_team_ids) == 2


def test_the_day_state_and_game_counts_come_off_the_schedule() -> None:
    snap = assemble(_inputs())
    assert snap.day_state == "midweek"
    assert (snap.games_final, snap.games_total) == (1, 3)
    assert snap.schedule_available


def test_without_a_schedule_nobody_is_done_and_the_day_is_unknown() -> None:
    snap = assemble(_inputs(games=None))
    assert not snap.schedule_available
    assert snap.day_state == "unknown"
    assert (snap.games_final, snap.games_total) == (0, 0)
    assert {s.status for t in snap.live_teams() for s in t.starters} == {"remaining"}


def test_moves_are_grouped_per_transaction_and_team_and_named() -> None:
    when = NOW - timedelta(hours=2)
    league = fixture_snapshot(week=WEEK)
    kept = league.teams[0].holdings[8].sleeper_player_id  # a bench player on team 1
    rows = [
        MoveRow(7, "waiver", when, 101, kept, "add", 12),
        MoveRow(7, "waiver", when, 101, "p-gone", "drop", 12),
        MoveRow(8, "trade", when - timedelta(hours=1), 102, "p03b0", "add", None),
        MoveRow(8, "trade", when - timedelta(hours=1), 103, "p03b0", "drop", None),
    ]
    snap = assemble(_inputs(moves=rows))
    assert [(m.kind, m.team_label, m.adds, m.drops, m.waiver_bid) for m in snap.moves] == [
        ("trade", "Member02", ("Bench 03-0",), (), None),
        ("trade", "Member03", (), ("Bench 03-0",), None),
        ("waiver", "Member01", (league.teams[0].holdings[8].player_name,), ("Gone Player",), 12),
    ]


def test_an_unnamed_player_in_a_move_keeps_his_id_rather_than_vanishing() -> None:
    rows = [MoveRow(7, "free_agent", NOW, 101, "p-unknown", "add", None)]
    snap = assemble(_inputs(moves=rows))
    assert snap.moves[0].adds == ("p-unknown",)


def test_local_midnight_is_the_start_of_the_central_day() -> None:
    # 04:50 UTC on the 12th is 11:50 PM on the 11th in Chicago (CDT, UTC-5).
    assert local_midnight(NOW) == datetime(2026, 10, 11, 5, 0, tzinfo=UTC)


# -- the reads, against the local database ------------------------------


class _ScheduleClient:
    def __init__(self, payload: list | Exception) -> None:
        self._payload = payload

    def get_schedule(self, season: int) -> list:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _schedule() -> list[dict]:
    return [
        {
            "status": "complete",
            "date": "2098-09-25",
            "home": "PHI",
            "week": db_seed.WEEK,
            "game_id": "a",
            "away": "DAL",
        },
        {
            "status": "pre_game",
            "date": "2098-09-27",
            "home": "KC",
            "week": db_seed.WEEK,
            "game_id": "b",
            "away": "DEN",
        },
    ]


def test_load_snapshot_reads_everything_off_the_seeded_league(conn) -> None:
    _season_id, teams = db_seed.seed_league(conn)
    snap = load_snapshot(conn, _ScheduleClient(_schedule()), db_seed.NOW)

    assert snap.week == db_seed.WEEK
    assert {t.team_id for t in snap.teams} == set(teams.values())
    one = snap.team(teams[1])
    assert one.label == "Nick1"
    assert one.points == Decimal(50 + 10 + db_seed.WEEK)
    assert [s.status for s in one.starters] == ["done", "remaining"]
    assert one.starters[0].points == Decimal("12.50")
    assert one.starters[0].nfl_team == "PHI"
    two = snap.team(teams[2])
    assert [s.status for s in two.starters] == ["out", "remaining"]
    assert two.starters[1].injury_status == "Questionable"
    three = snap.team(teams[3])
    assert three.is_eliminated and three.eliminated_week == 2
    assert snap.starter_slots == 2
    assert snap.scores_synced_at == db_seed.SEEDED_AT


def test_load_snapshot_takes_the_gulag_from_the_events(conn) -> None:
    _season_id, teams = db_seed.seed_league(conn)
    snap = load_snapshot(conn, _ScheduleClient(_schedule()), db_seed.NOW)
    assert snap.phase.gulag_source == "events"
    assert snap.phase.gulag_team_ids == tuple(sorted((teams[1], teams[2])))


def test_the_repository_reads_past_weeks_and_today_s_moves_only(conn) -> None:
    season_id, teams = db_seed.seed_league(conn)
    repo = EodRepository(conn)
    past = repo.past_scores(season_id, db_seed.WEEK)
    assert sorted(past) == [1, 2]
    assert past[1][teams[1]] == Decimal(61)
    moves = repo.moves_since(season_id, local_midnight(db_seed.NOW))
    assert {m.transaction_id for m in moves} and len(moves) == 2
    assert {(m.sleeper_player_id, m.action) for m in moves} == {("p1b", "add"), ("p9z", "drop")}
    assert all(m.waiver_bid == 12 for m in moves)
    assert repo.player_names(["p9z", "nobody"]) == {"p9z": "Nine Z"}


def test_a_schedule_outage_still_yields_a_snapshot(conn) -> None:
    db_seed.seed_league(conn)
    snap = load_snapshot(conn, _ScheduleClient(RuntimeError("down")), db_seed.NOW)
    assert not snap.schedule_available
    assert snap.day_state == "unknown"


def test_the_moves_window_starts_at_the_previous_post_or_a_day_back() -> None:
    """Ben's cadence skips Tuesdays and Saturdays, so "today" is the wrong window: the
    league wants everything since it last heard from the bot, capped so an outage does
    not replay a week of claims."""
    assert moves_window_start(NOW, None) == NOW - timedelta(hours=24)
    assert moves_window_start(NOW, NOW - timedelta(hours=30)) == NOW - timedelta(hours=30)
    assert moves_window_start(NOW, NOW - timedelta(days=10)) == NOW - timedelta(days=4)


def test_the_snapshot_carries_its_moves_window() -> None:
    snap = assemble(_inputs())
    assert snap.moves_since == NOW - timedelta(hours=24)


def test_the_repository_reads_the_previous_post_and_widens_the_window_to_it(conn) -> None:
    from ultimate_guillotine.summary.store import SummaryRepository

    season_id, _teams = db_seed.seed_league(conn)
    repo = EodRepository(conn)
    assert repo.previous_post_at(season_id) is None
    # A post sent 60 hours ago: the 50-hour-old claim is now inside the window.
    recap_id = SummaryRepository(conn).record_recap(
        season_id, db_seed.WEEK, "eod:2098-09-24", "2026.1", "hash", "body"
    )
    SummaryRepository(conn).mark_sent(recap_id)
    with conn.cursor() as cur:
        cur.execute(
            "update public.recaps set created_at = %s where id = %s",
            (db_seed.NOW - timedelta(hours=60), recap_id),
        )
    assert repo.previous_post_at(season_id) == db_seed.NOW - timedelta(hours=60)
    snap = load_snapshot(conn, _ScheduleClient(_schedule()), db_seed.NOW)
    assert snap.moves_since == db_seed.NOW - timedelta(hours=60)
    assert len(snap.moves) == 2
