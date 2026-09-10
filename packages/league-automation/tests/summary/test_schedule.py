"""The schedule feed: what a game's status means for the starters in it.

Sleeper's public schedule (``/schedule/nfl/regular/{season}``) is the one source of
"has this player played yet", so every odds number in the EOD summary rests on
reading it correctly. These cases pin the parse, the per-team index, the status
words, and the day-state verdict the header is written from.
"""

from datetime import date

from ultimate_guillotine.summary.schedule import (
    Game,
    day_state,
    game_state,
    games_final,
    games_for_week,
    parse_schedule,
)

PAYLOAD = [
    {
        "status": "complete",
        "date": "2026-09-10",
        "home": "PHI",
        "week": 1,
        "game_id": "a",
        "away": "DAL",
    },
    {
        "status": "pre_game",
        "date": "2026-09-13",
        "home": "CAR",
        "week": 1,
        "game_id": "b",
        "away": "CHI",
    },
    {
        "status": "in_game",
        "date": "2026-09-13",
        "home": "KC",
        "week": 1,
        "game_id": "c",
        "away": "DEN",
    },
    {
        "status": "pre_game",
        "date": "2026-09-20",
        "home": "KC",
        "week": 2,
        "game_id": "d",
        "away": "LAC",
    },
    {"junk": True},
    {"status": "pre_game", "week": "x", "home": "NE", "away": "NYJ", "game_id": "e"},
    "not even an object",
]


def _game(game_id: str, status: str, week: int = 1) -> Game:
    return Game(
        game_id=game_id, week=week, date=None, home="H" + game_id, away="A" + game_id, status=status
    )


def test_parse_keeps_well_formed_games_and_drops_the_rest() -> None:
    games = parse_schedule(PAYLOAD)
    assert [g.game_id for g in games] == ["a", "b", "c", "d"]
    assert games[0].date == date(2026, 9, 10)
    assert (games[0].home, games[0].away, games[0].week) == ("PHI", "DAL", 1)


def test_a_missing_or_unreadable_date_is_none_not_fatal() -> None:
    games = parse_schedule(
        [
            {
                "status": "pre_game",
                "date": "soon",
                "home": "NE",
                "week": 1,
                "game_id": "z",
                "away": "NYJ",
            }
        ]
    )
    assert games[0].date is None


def test_games_for_week_indexes_both_sides_of_every_game() -> None:
    by_team = games_for_week(parse_schedule(PAYLOAD), 1)
    assert by_team["PHI"].game_id == "a"
    assert by_team["DAL"].game_id == "a"
    assert by_team["KC"].game_id == "c"
    assert "LAC" not in by_team


def test_game_state_reads_the_status_word() -> None:
    assert game_state(_game("a", "complete")) == "done"
    assert game_state(_game("a", "canceled")) == "done"
    assert game_state(_game("a", "pre_game")) == "remaining"
    assert game_state(_game("a", "in_game")) == "live"


def test_a_status_this_build_has_never_seen_reads_as_live() -> None:
    """The conservative reading: a game in some state we cannot name may still be
    scoring, so its starters keep their variance rather than being called done."""
    assert game_state(_game("a", "halftime")) == "live"


def test_day_state_is_outlook_before_any_kickoff() -> None:
    by_team = games_for_week([_game("a", "pre_game"), _game("b", "pre_game")], 1)
    assert day_state(by_team) == "outlook"


def test_day_state_is_midweek_with_games_on_both_sides() -> None:
    by_team = games_for_week([_game("a", "complete"), _game("b", "pre_game")], 1)
    assert day_state(by_team) == "midweek"


def test_day_state_is_midweek_while_a_game_is_live() -> None:
    by_team = games_for_week([_game("a", "complete"), _game("b", "in_game")], 1)
    assert day_state(by_team) == "midweek"


def test_day_state_is_final_once_every_game_is_done() -> None:
    by_team = games_for_week([_game("a", "complete"), _game("b", "canceled")], 1)
    assert day_state(by_team) == "final"


def test_day_state_with_no_games_is_unknown() -> None:
    assert day_state({}) == "unknown"


def test_games_final_counts_distinct_games_not_team_entries() -> None:
    by_team = games_for_week(parse_schedule(PAYLOAD), 1)
    assert games_final(by_team) == (1, 3)
