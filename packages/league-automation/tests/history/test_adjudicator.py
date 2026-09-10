from decimal import Decimal

import pytest

from ultimate_guillotine.history.adjudicator import Unresolved, adjudicate, expected_remaining


def scores(teams):
    return {t: Decimal(t) for t in teams}


def test_week_one_qualifies_two_and_cuts_nobody():
    result = adjudicate(1, set(range(1, 19)), (), scores(range(1, 19)))
    assert result.qualifiers == (1, 2)
    assert len(result.alive) == 18
    assert {e.kind for e in result.events} == {'gulag_qualified'}


def test_gulag_loser_is_separate_from_pool_and_winner_not_reselected():
    result = adjudicate(2, set(range(1, 19)), (1, 2), scores(range(1, 19)))
    assert result.qualifiers == (3, 4)
    assert {e.team for e in result.events if e.kind == 'eliminated'} == {1}
    assert 2 in result.alive


def test_paid_champion_takes_penalty_and_loss_not_beneficiary():
    values = scores(range(1, 19))
    values[3] = Decimal(-1)
    result = adjudicate(2, set(range(1, 19)), (1, 2), values, {1: 3})
    cut = next(e for e in result.events if e.kind == 'eliminated')
    assert (cut.team, cut.qualifier) == (3, 1)
    assert 1 in result.alive
    assert {e.team for e in result.events if e.kind == 'gulag_entered'} == {2, 3}


def test_full_season_distinct_cuts_and_special_weeks():
    alive = set(range(1, 19))
    pair = ()
    eliminated = set()
    for week in range(1, 18):
        result = adjudicate(week, alive, pair, scores(alive))
        cuts = {e.team for e in result.events if e.kind == 'eliminated'}
        assert not cuts & eliminated
        assert len(cuts) == (0 if week == 1 else 2 if week == 12 else 1)
        assert len(result.alive) == expected_remaining(week)
        if week >= 12:
            assert result.qualifiers == ()
        eliminated |= cuts
        alive, pair = set(result.alive), result.qualifiers
    assert len(eliminated) == 17
    assert [e.team for e in result.events if e.kind == 'champion'] == list(alive)


def test_selection_boundary_tie_needs_ruling_but_tie_between_two_qualifiers_does_not():
    values = scores(range(1, 19))
    values[1] = values[2] = Decimal(1)
    assert adjudicate(1, set(values), (), values).qualifiers == (1, 2)
    values[3] = Decimal(1)
    with pytest.raises(Unresolved, match='tied'):
        adjudicate(1, set(values), (), values)
    assert adjudicate(1, set(values), (), values, tie_order=(3, 2, 1)).qualifiers == (3, 2)


def test_gulag_tie_missing_score_and_duplicate_substitutes_fail_closed():
    values = scores(range(1, 19))
    values[2] = values[1]
    with pytest.raises(Unresolved, match='tied'):
        adjudicate(2, set(values), (1, 2), values)
    with pytest.raises(Unresolved, match='missing'):
        adjudicate(1, set(range(1, 19)), (), {1: Decimal(0)})
    with pytest.raises(Unresolved, match='distinct'):
        adjudicate(2, set(values), (1, 2), values, {1: 2})
