"""Starter classification: who has played, who is left, who is out, who is missing.

The out rule is the board's own (`apps/web/src/board/derive/availability.ts`):
an unavailable status is out whatever the projection, and any other known flag
is out once Sleeper has withdrawn the number behind it. It is restated here so
the chat and the site can never disagree about who is playing.
"""

from decimal import Decimal
from types import MappingProxyType

from ultimate_guillotine.agent.tools.snapshot import LeagueHolding
from ultimate_guillotine.summary.lineup import (
    build_starters,
    classify_starter,
    coverage_pct,
    is_out,
    position_medians,
)
from ultimate_guillotine.summary.models import PlayerInfo, StarterLine, TeamLine
from ultimate_guillotine.summary.schedule import Game

WEEK = 4
DONE = Game(game_id="g1", week=WEEK, date=None, home="PHI", away="DAL", status="complete")
PRE = Game(game_id="g2", week=WEEK, date=None, home="KC", away="DEN", status="pre_game")
LIVE = Game(game_id="g3", week=WEEK, date=None, home="SF", away="SEA", status="in_game")
GAMES = {"PHI": DONE, "DAL": DONE, "KC": PRE, "DEN": PRE, "SF": LIVE, "SEA": LIVE}


def _holding(
    pid: str,
    slot_index: int,
    position: str = "RB",
    points: str | None = "12.5",
    lineup_position: str | None = None,
) -> LeagueHolding:
    return LeagueHolding(
        sleeper_player_id=pid,
        player_name=f"Player {pid}",
        position=position,
        slot="starter",
        lineup_position=lineup_position or position,
        slot_index=slot_index,
        week=WEEK,
        projected_points=MappingProxyType({} if points is None else {WEEK: Decimal(points)}),
    )


def _starter(
    status: str, position: str = "RB", projected: str | None = "10", team_id: int = 1
) -> StarterLine:
    return StarterLine(
        sleeper_player_id=f"p-{position}-{status}",
        name="x",
        position=position,
        lineup_position=position,
        nfl_team="KC",
        injury_status=None,
        projected=None if projected is None else Decimal(projected),
        points=Decimal(0),
        status=status,
    )


def _team(team_id: int, starters: tuple[StarterLine, ...], eliminated: bool = False) -> TeamLine:
    return TeamLine(
        team_id=team_id,
        member_id=team_id,
        label=f"Member{team_id:02d}",
        team_name=f"Team {team_id}",
        faab_remaining=100,
        is_eliminated=eliminated,
        eliminated_week=None,
        points=Decimal(0),
        starters=starters,
        scores_synced_at=None,
        has_score_row=True,
    )


# -- the out rule -------------------------------------------------------


def test_an_unavailable_status_is_out_whatever_the_projection() -> None:
    for status in ("Out", "IR", "PUP", "Sus", "COV", "DNR"):
        assert is_out(status, Decimal("14.0")), status


def test_a_known_flag_with_no_projection_is_out() -> None:
    for status in ("Questionable", "Doubtful", "NA"):
        assert is_out(status, None), status


def test_a_questionable_starter_with_a_projection_is_playing() -> None:
    assert not is_out("Questionable", Decimal("9.1"))
    assert not is_out("Doubtful", Decimal("9.1"))


def test_no_flag_is_never_out_even_with_no_projection() -> None:
    assert not is_out(None, None)
    assert not is_out("", None)


def test_an_unknown_flag_never_takes_a_starter_out() -> None:
    """Guessing a player out of a lineup on a word this build has never read is the
    worse error, the same call the sync and the board already make."""
    assert not is_out("Probable", None)


# -- classification -----------------------------------------------------


def test_out_wins_over_the_game_state() -> None:
    assert classify_starter("Out", Decimal(10), "KC", GAMES, True) == "out"


def test_no_game_this_week_is_a_bye() -> None:
    assert classify_starter(None, Decimal(10), "NYJ", GAMES, True) == "bye"


def test_the_game_state_names_done_remaining_and_live() -> None:
    assert classify_starter(None, Decimal(10), "PHI", GAMES, True) == "done"
    assert classify_starter(None, Decimal(10), "DEN", GAMES, True) == "remaining"
    assert classify_starter(None, Decimal(10), "SEA", GAMES, True) == "live"


def test_a_player_with_no_nfl_team_is_remaining_when_projected_else_done() -> None:
    """The directory has no team for him, so his game cannot be found. A projection
    says Sleeper expects him to score, so he keeps his variance; without one there
    is nothing to simulate and nothing to wait for."""
    assert classify_starter(None, Decimal(10), None, GAMES, True) == "remaining"
    assert classify_starter(None, None, None, GAMES, True) == "done"


def test_with_no_schedule_every_fit_starter_is_remaining() -> None:
    """Without the feed nobody can be called done. The caller withholds the odds in
    that case; classification just refuses to guess a game happened."""
    assert classify_starter(None, Decimal(10), "PHI", {}, False) == "remaining"
    assert classify_starter("Out", Decimal(10), "PHI", {}, False) == "out"


# -- building a lineup --------------------------------------------------


def test_build_starters_reads_points_team_and_flag_off_the_inputs() -> None:
    holdings = [_holding("p1", 0, "QB", "18.0"), _holding("p2", 1, "RB", "12.0")]
    players = {"p1": PlayerInfo("PHI", None), "p2": PlayerInfo("KC", "Questionable")}
    starters = build_starters(
        holdings,
        players=players,
        points={"p1": 21.4},
        week_games=GAMES,
        schedule_available=True,
        starter_slots=2,
    )
    assert [s.status for s in starters] == ["done", "remaining"]
    assert starters[0].points == Decimal("21.40")
    assert starters[1].points == Decimal(0)
    assert starters[1].injury_status == "Questionable"
    assert starters[1].nfl_team == "KC"
    assert starters[0].projected == Decimal("18.0")


def test_build_starters_appends_one_empty_line_per_unfilled_slot() -> None:
    holdings = [_holding("p1", 0, "QB")]
    starters = build_starters(
        holdings,
        players={"p1": PlayerInfo("PHI", None)},
        points={},
        week_games=GAMES,
        schedule_available=True,
        starter_slots=3,
    )
    assert [s.status for s in starters] == ["done", "empty", "empty"]
    assert starters[1].sleeper_player_id is None
    assert starters[1].projected is None


def test_build_starters_keeps_lineup_order() -> None:
    holdings = [_holding("p2", 1, "RB"), _holding("p1", 0, "QB")]
    players = {"p1": PlayerInfo("PHI", None), "p2": PlayerInfo("PHI", None)}
    starters = build_starters(
        holdings,
        players=players,
        points={},
        week_games=GAMES,
        schedule_available=True,
        starter_slots=2,
    )
    assert [s.sleeper_player_id for s in starters] == ["p1", "p2"]


def test_a_player_the_directory_does_not_know_still_gets_a_line() -> None:
    holdings = [_holding("mystery", 0, "RB")]
    starters = build_starters(
        holdings,
        players={},
        points={},
        week_games=GAMES,
        schedule_available=True,
        starter_slots=1,
    )
    assert starters[0].nfl_team is None
    assert starters[0].status == "remaining"


# -- coverage over the players who can still score ---------------------


def test_coverage_counts_only_pending_starters_on_live_teams() -> None:
    teams = [
        _team(
            1,
            (
                _starter("remaining"),
                _starter("remaining", projected=None),
                _starter("done", projected=None),
            ),
        ),
        _team(
            2,
            (_starter("live"), _starter("out", projected=None), _starter("empty", projected=None)),
        ),
        _team(3, (_starter("remaining", projected=None),), eliminated=True),
    ]
    # Three pending starters on live teams, two of them projected.
    assert coverage_pct(teams) == Decimal("66.67")


def test_coverage_is_full_when_nothing_is_pending() -> None:
    teams = [_team(1, (_starter("done"), _starter("out", projected=None)))]
    assert coverage_pct(teams) == Decimal("100.00")


def test_position_medians_come_from_every_projected_starter() -> None:
    teams = [
        _team(
            1,
            (
                _starter("done", "RB", "10"),
                _starter("remaining", "RB", "20"),
                _starter("remaining", "WR", "7"),
            ),
        ),
        _team(2, (_starter("remaining", "RB", "16"), _starter("remaining", "WR", None))),
    ]
    medians = position_medians(teams)
    assert medians["RB"] == Decimal(16)
    assert medians["WR"] == Decimal(7)
    assert "TE" not in medians
