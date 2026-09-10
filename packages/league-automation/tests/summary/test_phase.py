"""The rules phase: what this week's adverse event is, and who is in the gulag.

The week table is the season simulation in the rules document. The gulag pairing
is read from the Adjudicator's events when they exist and replayed from stored
scores when they do not; the replay is provisional by design and these cases pin
exactly what it can and cannot see.
"""

from decimal import Decimal

import pytest

from ultimate_guillotine.summary.phase import (
    gulag_from_events,
    phase_kind,
    replay_gulag,
    resolve_phase,
)

TEAMS = tuple(range(1, 7))


def _scores(**weeks: dict[int, str]) -> dict[int, dict[int, Decimal]]:
    return {
        int(week.removeprefix("w")): {team: Decimal(points) for team, points in rows.items()}
        for week, rows in weeks.items()
    }


@pytest.mark.parametrize(
    ("week", "kind"),
    [
        (1, "entry"),
        (2, "gulag"),
        (11, "gulag"),
        (12, "double"),
        (13, "cut"),
        (16, "cut"),
        (17, "final"),
        (18, "over"),
        (25, "over"),
    ],
)
def test_the_week_table_matches_the_rules_document(week: int, kind: str) -> None:
    assert phase_kind(week) == kind


def test_events_for_the_week_name_the_pair() -> None:
    events = [
        (2, "gulag_entry", {"team_id": 5}),
        (2, "gulag_entry", {"team_id": 7}),
        (3, "gulag_entry", {"team_id": 9}),
        (2, "elimination", {"team_id": 4}),
    ]
    assert gulag_from_events(events, 2) == (5, 7)


def test_a_single_event_is_not_a_pairing() -> None:
    """Half a ruling is no ruling: the caller falls back to the replay rather than
    fielding a gulag of one."""
    assert gulag_from_events([(2, "gulag_entry", {"team_id": 5})], 2) is None


def test_an_event_with_no_usable_team_id_is_ignored() -> None:
    """A payload with no id, or a string where the id should be, names nobody; the
    two well-formed rows still make the pair."""
    events = [
        (2, "gulag_entry", {}),
        (2, "gulag_entry", {"team_id": "9"}),
        (2, "gulag_entry", {"team_id": 7}),
        (2, "gulag_entry", {"team_id": 5}),
    ]
    assert gulag_from_events(events, 2) == (5, 7)
    assert gulag_from_events(events[:3], 2) is None


def test_replay_week_2_is_the_bottom_two_of_week_1() -> None:
    scores = _scores(w1={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"})
    assert replay_gulag(2, scores, {}, TEAMS) == (5, 6)


def test_replay_excludes_last_weeks_gulag_from_the_pool() -> None:
    """Week 2's gulag pair (5, 6) fight each other; the week 3 gulag comes from the
    bottom two of the *other* four, even though 5 and 6 scored less again."""
    scores = _scores(
        w1={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"},
        w2={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"},
    )
    assert replay_gulag(3, scores, {6: 2}, TEAMS) == (3, 4)


def test_replay_leaves_out_a_team_from_the_week_it_was_eliminated_after() -> None:
    """Team 6 lost the week 2 gulag: alive in week 2, gone from week 3 on."""
    scores = _scores(
        w1={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"},
        w2={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"},
        w3={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "10"},
    )
    # Week 3 gulag is (3, 4); week 4's comes from the pool {1, 2, 5}: bottom two 2 and 5.
    assert replay_gulag(4, scores, {6: 2, 4: 3}, TEAMS) == (2, 5)


def test_replay_excludes_an_eliminated_team_with_no_recorded_week() -> None:
    """When nobody wrote down when a team went out it is left out of every replayed
    week: it cannot be placed, and guessing a pairing around it is worse than a pool
    of one fewer."""
    scores = _scores(w1={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"})
    assert replay_gulag(2, scores, {6: None}, TEAMS) == (4, 5)


def test_replay_with_a_missing_week_is_unknown() -> None:
    scores = _scores(w1={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"})
    assert replay_gulag(3, scores, {}, TEAMS) is None


def test_replay_with_too_few_scored_teams_is_unknown() -> None:
    scores = _scores(w1={1: "100"})
    assert replay_gulag(2, scores, {}, TEAMS) is None


def test_replay_breaks_a_tie_by_team_id() -> None:
    scores = _scores(w1={1: "100", 2: "50", 3: "50", 4: "50"})
    assert replay_gulag(2, scores, {}, (1, 2, 3, 4)) == (2, 3)


def test_resolve_prefers_the_events_over_the_replay() -> None:
    scores = _scores(w1={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"})
    events = [(2, "gulag_entry", {"team_id": 1}), (2, "gulag_entry", {"team_id": 2})]
    phase = resolve_phase(2, events, scores, {}, TEAMS)
    assert (phase.kind, phase.gulag_team_ids, phase.gulag_source) == ("gulag", (1, 2), "events")


def test_resolve_replays_when_there_are_no_events() -> None:
    scores = _scores(w1={1: "100", 2: "90", 3: "80", 4: "70", 5: "60", 6: "50"})
    phase = resolve_phase(2, [], scores, {}, TEAMS)
    assert (phase.gulag_team_ids, phase.gulag_source) == ((5, 6), "replay")


def test_resolve_reports_an_unknown_pairing() -> None:
    phase = resolve_phase(3, [], {}, {}, TEAMS)
    assert (phase.kind, phase.gulag_team_ids, phase.gulag_source) == ("gulag", (), "unknown")


def test_week_1_has_no_gulag() -> None:
    phase = resolve_phase(1, [], {}, {}, TEAMS)
    assert (phase.kind, phase.gulag_team_ids, phase.gulag_source) == ("entry", (), "none")


def test_the_cut_weeks_have_no_gulag() -> None:
    scores = {w: {t: Decimal(100 - t) for t in TEAMS} for w in range(1, 13)}
    phase = resolve_phase(13, [], scores, {}, TEAMS)
    assert (phase.kind, phase.gulag_team_ids, phase.gulag_source) == ("cut", (), "none")
