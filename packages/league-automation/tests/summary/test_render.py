"""The message: every section, in the words the league will read.

Small leagues built from the helpers pin each section's wording; the closed-form
fixture pins the whole thing's size and that no team is left out.
"""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from tests.summary.helpers import NOW, done_team, phase, snapshot, starter, team
from ultimate_guillotine.summary.color import EodColor
from ultimate_guillotine.summary.fixture import FIXTURE_NOW, fixture_eod
from ultimate_guillotine.summary.models import EodPacket, Move
from ultimate_guillotine.summary.render import View, facts_text, percent, render, window_stamp
from ultimate_guillotine.summary.survival import simulate


def _packet(snap, *, odds: bool = True, reason: str | None = None) -> EodPacket:
    result = simulate(snap, simulations=200) if odds else None
    return EodPacket(
        snapshot=snap,
        result=result,
        coverage_pct=Decimal(100),
        no_odds_reason=None if odds else (reason or "no schedule"),
    )


def _entry_week():
    return snapshot(
        (done_team(1, "100"), done_team(2, "90"), done_team(3, "80"), done_team(4, "70.5")),
        week=1,
        day_state="final",
        games_final=16,
        games_total=16,
    )


# -- header ---------------------------------------------------------------


def test_the_header_names_the_week_the_day_and_the_games() -> None:
    snap = snapshot(
        (
            done_team(1, "100"),
            done_team(2, "90"),
            done_team(3, "80"),
            team(4, points="0", starters=(starter("remaining"),)),
        ),
        week=3,
        phase_=phase(3, "gulag", gulag=(1, 2), source="events"),
    )
    text = render(_packet(snap), None, NOW)
    lines = text.splitlines()
    assert lines[0] == "🗡️ GUILLOTINE DAILY · Week 3 · Sunday"
    assert lines[1] == "13 of 16 games final · 1 team still has players to go"


def test_the_outlook_header_says_nothing_has_kicked_off() -> None:
    snap = snapshot(
        (
            team(1, starters=(starter("remaining"),)),
            team(2, starters=(starter("remaining"),)),
            team(3, starters=(starter("remaining"),)),
        ),
        day_state="outlook",
        games_final=0,
    )
    assert render(_packet(snap), None, NOW).splitlines()[1] == (
        "Nothing has kicked off yet · the projected board"
    )


def test_the_final_header_says_the_week_is_in_the_books() -> None:
    assert render(_packet(_entry_week()), None, NOW).splitlines()[1] == (
        "Every game is in the books · standings pending the commish"
    )


def test_the_unknown_header_says_the_schedule_was_unreachable() -> None:
    snap = snapshot(
        (done_team(1, "1"), done_team(2, "2"), done_team(3, "3")),
        day_state="unknown",
        schedule_available=False,
        games_final=0,
        games_total=0,
    )
    assert render(_packet(snap, odds=False), None, NOW).splitlines()[1] == (
        "Game status unavailable tonight"
    )


# -- colour ---------------------------------------------------------------


def test_the_colour_sits_under_the_header_when_there_is_one() -> None:
    color = EodColor(headline="Four scores, two graves", blurb="Member04 is toast.")
    text = render(_packet(_entry_week()), color, NOW)
    lines = text.splitlines()
    assert lines[3] == "🔥 Four scores, two graves"
    assert lines[4] == "Member04 is toast."


def test_no_colour_leaves_no_gap() -> None:
    text = render(_packet(_entry_week()), None, NOW)
    assert "🔥" not in text
    assert text.splitlines()[3].startswith("⚰️")


# -- the gulag ------------------------------------------------------------


def test_the_gulag_pair_are_listed_by_their_odds_of_losing() -> None:
    teams = (
        done_team(1, "100"),
        done_team(2, "95"),
        done_team(3, "60"),
        done_team(4, "50"),
        done_team(5, "70"),
        done_team(6, "80"),
    )
    snap = snapshot(teams, week=5, phase_=phase(5, "gulag", gulag=(5, 6), source="events"))
    text = render(_packet(snap), None, NOW)
    assert "⚔️ THE GULAG · loser is out" in text
    gulag = text.split("⚔️ THE GULAG · loser is out\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert gulag[0] == "Member05 · locked to lose · original 12 · current 70 · actual 70.0"
    assert gulag[1] == "Member06 · safe · original 12 · current 80 · actual 80.0"
    assert "inferred" not in text


def test_a_replayed_pairing_is_called_provisional() -> None:
    teams = (done_team(1, "100"), done_team(2, "95"), done_team(3, "60"), done_team(4, "50"))
    snap = snapshot(teams, week=5, phase_=phase(5, "gulag", gulag=(3, 4), source="replay"))
    assert "(pairing inferred from last week's scores)" in render(_packet(snap), None, NOW)


def test_an_unknown_pairing_is_said_and_everyone_is_the_pool() -> None:
    teams = (done_team(1, "100"), done_team(2, "95"), done_team(3, "60"), done_team(4, "50"))
    snap = snapshot(teams, week=5, phase_=phase(5, "gulag", gulag=(), source="unknown"))
    text = render(_packet(snap), None, NOW)
    assert "⚔️ THE GULAG · pairing unknown (a past week has no scores on file)" in text
    assert "⚰️ ON THE BLOCK · bottom 2 enter the Week 6 gulag" in text


# -- on the block ---------------------------------------------------------


def test_the_block_names_the_two_likeliest_and_who_is_sweating() -> None:
    teams = (
        done_team(1, "100"),
        done_team(2, "52"),
        done_team(3, "50"),
        team(4, points="45", starters=(starter("remaining", projected="10"),)),
        team(5, points="40", starters=(starter("remaining", projected="20"),)),
    )
    text = render(_packet(snapshot(teams)), None, NOW)
    block = text.split("⚰️ ON THE BLOCK · bottom 2 enter the Week 2 gulag\n", 1)[1]
    block = block.split("\n\n", 1)[0].splitlines()
    # Ben's line: the team, its risk, its projected finish, its actual score.
    assert len(block) == 2
    assert re.fullmatch(
        r"Member0\d · \d+% · original \d+ · current \d+ · actual \d+\.\d", block[0]
    ), block[0]
    sweating = text.split("⚰️ SWEATING\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert 1 <= len(sweating) <= 2
    assert all(
        re.fullmatch(r"Member0\d · \d+% · original \d+ · current \d+ · actual \d+\.\d", s)
        for s in sweating
    )
    assert "Member01" not in text.split("⚰️ SWEATING\n", 1)[1].split("\n\n", 1)[0]


def test_a_cut_week_puts_one_team_on_the_block() -> None:
    snap = snapshot(
        (done_team(1, "100"), done_team(2, "95"), done_team(3, "60")),
        week=14,
        phase_=phase(14, "cut"),
        day_state="final",
    )
    text = render(_packet(snap), None, NOW)
    assert "⚰️ ON THE BLOCK · lowest score is cut" in text
    assert "Member03 · locked · original 12 · current 60 · actual 60.0" in text
    assert "SWEATING" not in text


def test_the_final_names_the_title_at_stake() -> None:
    snap = snapshot(
        (done_team(1, "100"), done_team(2, "95")),
        week=17,
        phase_=phase(17, "final"),
        day_state="final",
    )
    assert "🏆 THE FINAL · lower score is runner-up" in render(_packet(snap), None, NOW)


# -- the board ------------------------------------------------------------


def test_original_keeps_finished_and_out_estimates_but_requires_complete_data() -> None:
    complete = team(
        1,
        starters=(
            starter("done", projected="16.86", points="5.6"),
            starter("out", projected="10"),
            starter("remaining", projected="20"),
            starter("empty", projected=None),
        ),
    )
    missing = team(2, starters=(starter("done", projected=None),))
    empty = team(3, starters=(starter("empty", projected=None),))
    no_score = team(4, starters=(starter("remaining", projected="10"),), has_score_row=False)
    view = View(_packet(snapshot((complete, missing, empty, no_score)), odds=False))
    assert view.original_projected(complete) == "47"
    assert view.original_projected(missing) == "—"
    assert view.original_projected(empty) == "0"
    assert view.projected(complete) == "—"
    assert view.actual(no_score) == "—"


def test_the_board_ranks_by_projected_finish_and_marks_the_gulag_and_the_estimates() -> None:
    teams = (
        done_team(1, "100"),
        team(2, points="40", starters=(starter("remaining", projected="70"),)),
        done_team(3, "95"),
        team(
            4,
            points="0",
            starters=(
                starter("remaining", projected=None, position="RB"),
                starter("remaining", projected="30", position="RB"),
            ),
        ),
        done_team(5, "60"),
        done_team(6, "50"),
        done_team(7, "10", eliminated=True, eliminated_week=3),
    )
    snap = snapshot(teams, week=5, phase_=phase(5, "gulag", gulag=(5, 6), source="events"))
    text = render(_packet(snap), None, NOW)
    board = text.split("📊 THE BOARD · original proj · current proj · actual · left · risk\n", 1)[1]
    board = board.split("\n\n", 1)[0].splitlines()
    # Team 2 finishes at 110 on average but with a 35-point spread, so its risk of the
    # bottom two is open; team 1 at 100 with nothing left can never be there. Team 4's
    # unprojected back is drawn at the RB median (12), so its finish is an estimate.
    assert board[0].startswith("1. Member02 · 70 · 110 · 40.0 · 1 · ")
    assert board[1] == "2. Member01 · 12 · 100 · 100.0 · 0 · 0%"
    assert board[2].startswith("3. Member03 · 12 · 95 · 95.0 · 0 · ")
    assert board[3].startswith("4. Member05 · 12 · 60 · 60.0 · 0 · ⚔")
    assert board[4].startswith("5. Member06 · 12 · 50 · 50.0 · 0 · ⚔")
    assert board[5].startswith("6. Member04 · — · ~42 · 0.0 · 2 · ")
    assert board[6] == "Out: Member07 (wk 3)"


def test_before_kickoff_the_block_and_the_gulag_lines_carry_all_three_figures() -> None:
    """The three figures stay visible even before kickoff."""
    teams = (
        team(1, starters=(starter("remaining", projected="100"),)),
        team(2, starters=(starter("remaining", projected="90"),)),
        team(3, starters=(starter("remaining", projected="80"),)),
        team(4, starters=(starter("remaining", projected="70"),)),
        team(5, starters=(starter("remaining", projected="60"),)),
        team(6, starters=(starter("remaining", projected="50"),)),
    )
    snap = snapshot(
        teams,
        week=5,
        phase_=phase(5, "gulag", gulag=(5, 6), source="events"),
        day_state="outlook",
        games_final=0,
    )
    text = render(_packet(snap), None, NOW)
    gulag = text.split("⚔️ THE GULAG · loser is out\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert re.fullmatch(
        r"Member06 · \d+% to lose · original 50 · current 50 · actual 0\.0", gulag[0]
    ), gulag[0]
    assert "actual 0.0" in gulag[0] and " left" not in gulag[0]
    block = text.split("⚰️ ON THE BLOCK · bottom 2 enter the Week 6 gulag\n", 1)[1]
    assert re.fullmatch(
        r"Member04 · \d+% · original 70 · current 70 · actual 0\.0", block.splitlines()[0]
    )


def test_the_outlook_board_keeps_all_three_figures_and_drops_the_players_left() -> None:
    snap = snapshot(
        (
            team(1, starters=(starter("remaining", projected="100"),)),
            team(2, starters=(starter("remaining", projected="90"),)),
            team(3, starters=(starter("remaining", projected="80"),)),
        ),
        day_state="outlook",
        games_final=0,
    )
    text = render(_packet(snap), None, NOW)
    assert "📊 THE BOARD · original proj · current proj · actual · risk" in text
    assert "1. Member01 · 100 · 100 · 0.0 · " in text
    assert " left" not in text.split("📊 THE BOARD", 1)[1]


# -- roster watch ---------------------------------------------------------


def test_the_roster_watch_names_the_holes() -> None:
    teams = (
        team(1, starters=(starter("done"), starter("empty"))),
        team(2, starters=(starter("out", injury="Out", name="Hurt Guy"), starter("done"))),
        team(
            3, starters=(starter("out", injury="Questionable", projected=None, name="Doubt Guy"),)
        ),
        team(4, starters=(starter("remaining", projected=None, name="Nobody Knows"),)),
        done_team(5, "50"),
    )
    text = render(_packet(snapshot(teams)), None, NOW)
    watch = text.split("🩹 ROSTER WATCH\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert watch == [
        "Member01: 1 empty slot",
        "Member02: Hurt Guy (Out) still in the lineup",
        "Member03: Doubt Guy (Questionable, no projection)",
        "Member04: Nobody Knows has no projection",
    ]


def test_a_clean_league_has_no_roster_watch() -> None:
    assert "🩹" not in render(_packet(_entry_week()), None, NOW)


def test_the_roster_watch_is_capped() -> None:
    teams = tuple(team(i, starters=(starter("done"), starter("empty"))) for i in range(1, 12))
    text = render(_packet(snapshot(teams)), None, NOW)
    watch = text.split("🩹 ROSTER WATCH\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert len(watch) == 9
    assert watch[-1] == "+3 more"


# -- moves ----------------------------------------------------------------


def test_the_moves_line_says_who_added_and_dropped_whom() -> None:
    moves = (
        Move("waiver", NOW, "Member03", ("New Guy",), ("Old Guy",), 12),
        Move("trade", NOW, "Member08", ("Star",), (), None),
        Move("free_agent", NOW, "Member09", ("Pickup",), (), None),
    )
    snap = snapshot(
        (done_team(1, "1"), done_team(2, "2"), done_team(3, "3")),
        moves=moves,
        moves_since=NOW - timedelta(hours=48),
    )
    text = render(_packet(snap), None, NOW)
    # Friday 11:50 PM Central, two days before the Sunday-night `NOW`.
    lines = text.split("🔁 MOVES SINCE FRI 11:50 PM\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert lines == [
        "Member03: +New Guy −Old Guy (waiver $12)",
        "Member08: +Star (trade)",
        "Member09: +Pickup",
    ]


def test_no_moves_means_no_section() -> None:
    assert "🔁" not in render(_packet(_entry_week()), None, NOW)


def test_the_window_stamp_keeps_its_meridiem_upper_case() -> None:
    """Ben's paste read `moves since Wed 9:10 Am`: a title-casing slip."""
    assert window_stamp(NOW - timedelta(hours=48)) == "Fri 11:50 PM"


def test_a_moves_window_nobody_recorded_is_called_recent() -> None:
    moves = (Move("waiver", NOW, "Member03", ("New Guy",), (), None),)
    text = render(
        _packet(snapshot((done_team(1, "1"), done_team(2, "2"), done_team(3, "3")), moves=moves)),
        None,
        NOW,
    )
    assert "🔁 RECENT MOVES\n" in text


# -- footer and factual mode ---------------------------------------------


def test_the_footer_is_one_line_monte_carlo_projections_as_of() -> None:
    """Ben (2026-09-10): "instead of 10k sims right just write Monte Carlo projections
    as of X CST. no further commentary"."""
    text = render(_packet(_entry_week()), None, NOW)
    assert text.splitlines()[-1] == "Monte Carlo projections as of 11:50 PM CST"


def test_factual_mode_carries_no_percentage_and_says_why() -> None:
    teams = (
        done_team(1, "100"),
        done_team(2, "52"),
        done_team(3, "50"),
        team(4, points="45", starters=(starter("remaining", projected=None),)),
    )
    text = render(
        _packet(snapshot(teams), odds=False, reason="coverage 50% of remaining starters"), None, NOW
    )
    assert "%" not in text.replace("coverage 50%", "")
    assert text.splitlines()[-1] == (
        "No Monte Carlo odds: coverage 50% of remaining starters · data as of 11:50 PM CST"
    )
    assert "⚰️ ON THE BLOCK · bottom 2 enter the Week 2 gulag" in text
    block = text.split("⚰️ ON THE BLOCK · bottom 2 enter the Week 2 gulag\n", 1)[1]
    assert block.splitlines()[0] == "Member04 · original — · current — · actual 45.0"
    assert block.splitlines()[1] == "Member03 · original 12 · current — · actual 50.0"
    assert "SWEATING" not in text
    assert "📊 THE BOARD · original proj · current proj · actual · left" in text


def test_a_missing_scores_row_is_said_in_the_footer() -> None:
    snap = snapshot(
        (done_team(1, "100", has_score_row=False), done_team(2, "90"), done_team(3, "80"))
    )
    assert "1 team has no score on file" in render(_packet(snap), None, NOW)


def test_percent_rounds_whole_and_names_the_tails() -> None:
    assert percent(Decimal("0.3925"), settled=False) == "39%"
    assert percent(Decimal("0.004"), settled=False) == "<1%"
    assert percent(Decimal("0.996"), settled=False) == ">99%"
    assert percent(Decimal(0), settled=False) == "0%"
    assert percent(Decimal(1), settled=False) == "100%"
    assert percent(Decimal(1), settled=True) == "locked"
    assert percent(Decimal(0), settled=True) == "safe"


# -- the facts the model sees --------------------------------------------


def test_the_facts_text_is_the_middle_sections_only() -> None:
    packet = _packet(_entry_week())
    facts = facts_text(packet)
    assert facts.startswith("⚰️ ON THE BLOCK")
    assert "GUILLOTINE DAILY" not in facts
    assert "Monte Carlo" not in facts
    assert "📊 THE BOARD" in facts


# -- the whole thing ------------------------------------------------------


def test_the_fixture_message_names_every_live_team_and_fits_a_phone() -> None:
    snap = fixture_eod()
    text = render(_packet(snap), None, FIXTURE_NOW)
    for live in snap.live_teams():
        assert live.label in text
    assert "Out: Member17 (wk 5)" in text
    assert len(text) < 2500, len(text)
    assert "\n\n\n" not in text
    assert not text.endswith("\n")


def test_the_time_is_written_in_central_time() -> None:
    noon_utc = datetime(2026, 9, 13, 17, 0, tzinfo=UTC)
    text = render(_packet(_entry_week()), None, noon_utc)
    assert "as of 11:50 PM CST" in text  # the stamp is the data's own, not now
    assert text.splitlines()[0].endswith("· Sunday")
