"""Every trade the Advisor is allowed to suggest, checked against one fixture.

The tests are tables over the five asks the skill can receive -- acquire, move,
rental, a named counterparty, and an ask no honest trade answers -- because the
generator's contract is not "produces something plausible" but "produces exactly
these, in exactly this order, every time". A property that holds for one ask and
not another is the bug this module exists to catch.

Every expected number is computable by hand from ``tests.advisor.fixture``:
member 18 is on the cut line and short a running back, members 1, 2 and 5 are
the only teams carrying a spare one, and member 3 is long two wide receivers and
short nothing. Member 18 itself has *no* bench player above replacement at any
position, which is why the move ask is asked by member 3 -- asking it as member
18 is the "nothing to spare" row of the no-trade table instead.
"""

from collections import Counter
from dataclasses import replace
from decimal import Decimal
from itertools import pairwise

import pytest

from tests.advisor.fixture import (
    ELIMINATED_MEMBER_ID,
    NEAR_CUT_MEMBER_ID,
    fixture_snapshot,
)
from ultimate_guillotine.advisor.candidates import (
    FAAB_FLOOR,
    MAX_CANDIDATES,
    OFFERS_PER_COUNTERPARTY,
    generate_candidates,
)
from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.pricing import price_points
from ultimate_guillotine.advisor.scoring import score_league

#: The asker for every test but the move ask: on the cut line and short a back.
ASKER_MEMBER_ID = NEAR_CUT_MEMBER_ID
ASKER = "Member18"
#: The one team long at a position and short at none, so it has something to
#: move and a reason to listen. Member 18 has neither -- see the docstring.
SELLER_MEMBER_ID = 3
SELLER = "Member03"
#: A team whose needs are all zero: nothing it could acquire would help it.
STACKED_MEMBER_ID = 1
#: Short a running back and long a wide receiver at the same time, which is the
#: only way an "either" ask has both halves to merge.
TWO_WAY_MEMBER_ID = 9
ELIMINATED = "Member17"
#: An open ask by this team produces two candidates that fit equally well.
TIED_MEMBER_ID = 12


def _dark_snapshot():
    """The gate's hard case: team totals withheld, player rows as numeric as ever."""
    return fixture_snapshot(coverage_pct=Decimal("90.00"), keep_player_points=True)


DARK = _dark_snapshot()

#: ``Ask`` fields in order: positions, direction, horizon_weeks, rental,
#: named_counterparties, wants_numbers.
ACQUIRE_RB = Ask(("RB",), "acquire", None, False, (), False)
RENT_RB = Ask(("RB",), "acquire", 3, True, (), False)
MOVE_WR = Ask(("WR",), "move", None, False, (), False)
EITHER_RB = Ask(("RB",), "either", None, False, (), False)
NAMED_SELLER = Ask(("WR",), "acquire", None, False, (SELLER,), False)

#: The rental horizon the fixture's week 6 and a three-week ask produce.
RENTAL_RETURN_WEEK = 10
RENTAL_CONDITION = "returns before the Week 10 lock"

#: A single accepted trade: member 2 bought member 1's spare running back --
#: ``p01b0``, ``Bench 01-0`` -- for 80 FAAB. One player, one payment, so the
#: price point is the whole 80.
COMPARABLE_CODE = "T-2026-001"
COMPARABLE_FAAB = 80
#: More FAAB than any fixture team has left, so the price has to be clamped.
UNAFFORDABLE_FAAB = 500


def _comparable_rows(faab: int) -> list[dict]:
    return [
        {
            "trade_code": COMPARABLE_CODE,
            "season": 2026,
            "terms": {
                "kind": "permanent",
                "effective_week": 4,
                "assets": [
                    {
                        "kind": "player",
                        "from_member_id": 1,
                        "to_member_id": 2,
                        "player_id": "p01b0",
                        "player_name": "Bench 01-0",
                        "amount": None,
                        "unit": None,
                        "description": None,
                    },
                    {
                        "kind": "faab",
                        "from_member_id": 2,
                        "to_member_id": 1,
                        "player_id": None,
                        "player_name": None,
                        "amount": faab,
                        "unit": "faab",
                        "description": None,
                    },
                ],
                "parties": [],
                "special_terms": [],
            },
        }
    ]


#: Asks that no honest trade answers, and why each one is empty. Every row is a
#: real refusal rather than a shrug: an eliminated manager is out of the league,
#: a team with nothing above replacement has nothing to sell, a team with no
#: need cannot be helped by buying, and a counterparty nobody can match is not a
#: licence to propose a trade with somebody else instead.
NO_TRADE = (
    pytest.param(ACQUIRE_RB, ELIMINATED_MEMBER_ID, id="the-asker-is-eliminated"),
    pytest.param(MOVE_WR, ASKER_MEMBER_ID, id="the-asker-has-nothing-to-spare"),
    pytest.param(ACQUIRE_RB, STACKED_MEMBER_ID, id="the-asker-needs-nothing"),
    pytest.param(
        Ask(("RB",), "acquire", None, False, ("Member17",), False),
        ASKER_MEMBER_ID,
        id="the-only-named-counterparty-is-eliminated",
    ),
    pytest.param(
        Ask(("RB",), "acquire", None, False, ("Nobody",), False),
        ASKER_MEMBER_ID,
        id="the-named-counterparty-matches-nobody",
    ),
)


def _generate(ask, member_id=ASKER_MEMBER_ID, points=(), snapshot=None, **kwargs):
    snapshot = fixture_snapshot() if snapshot is None else snapshot
    return snapshot, generate_candidates(
        snapshot, score_league(snapshot), member_id, ask, list(points), **kwargs
    )


def _priced_points(faab=COMPARABLE_FAAB):
    snapshot = fixture_snapshot()
    positions = {h.sleeper_player_id: h.position for t in snapshot.teams for h in t.holdings}
    return price_points(_comparable_rows(faab), positions)


@pytest.mark.parametrize(
    ("ask", "member_id"),
    [
        pytest.param(ACQUIRE_RB, ASKER_MEMBER_ID, id="acquire"),
        pytest.param(RENT_RB, ASKER_MEMBER_ID, id="rental"),
        pytest.param(MOVE_WR, SELLER_MEMBER_ID, id="move"),
        pytest.param(NAMED_SELLER, ASKER_MEMBER_ID, id="named-counterparty"),
        pytest.param(EITHER_RB, ASKER_MEMBER_ID, id="either-direction"),
    ],
)
def test_candidates_are_capped_sorted_and_never_include_the_asker(ask, member_id) -> None:
    snapshot, candidates = _generate(ask, member_id)
    asker = snapshot.team_for_member(member_id)
    assert 0 < len(candidates) <= MAX_CANDIDATES
    scores = [c.fit_score for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert all(isinstance(c.fit_score, Decimal) for c in candidates)
    assert all(c.counterparty != asker.member_label for c in candidates)
    assert all(c.counterparty_member_id != member_id for c in candidates)


@pytest.mark.parametrize(
    ("ask", "member_id"),
    [
        pytest.param(ACQUIRE_RB, ASKER_MEMBER_ID, id="acquire"),
        pytest.param(MOVE_WR, SELLER_MEMBER_ID, id="move"),
    ],
)
def test_the_order_is_total_and_ties_break_on_the_counterparty_team_id(ask, member_id) -> None:
    """Same snapshot, same list, same order -- and no pair the sort cannot separate."""
    _, first = _generate(ask, member_id)
    _, second = _generate(ask, member_id)
    assert [c.sort_key for c in first] == [c.sort_key for c in second]
    keys = [c.sort_key for c in first]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)
    for earlier, later in pairwise(first):
        if earlier.fit_score == later.fit_score:
            assert earlier.counterparty_team_id <= later.counterparty_team_id


def test_the_order_does_not_depend_on_the_order_the_teams_arrive_in() -> None:
    """Two candidates that fit equally well are separated by the tie-break, not by luck.

    An open ask by member 12 produces a real tie, so a ranking that stopped at
    the fit score would hand back whichever of the two the roster query happened
    to yield first -- and the same question would get two different answers on
    two days that differed only in row order.
    """
    ask = Ask((), "either", None, False, (), False)
    snapshot = fixture_snapshot()
    reversed_snapshot = replace(snapshot, teams=tuple(reversed(snapshot.teams)))
    _, forward = _generate(ask, TIED_MEMBER_ID, snapshot=snapshot)
    _, backward = _generate(ask, TIED_MEMBER_ID, snapshot=reversed_snapshot)
    fits = [c.fit_score for c in forward]
    assert len(set(fits)) < len(fits), "this ask is only interesting because it ties"
    assert [c.sort_key for c in backward] == [c.sort_key for c in forward]


@pytest.mark.parametrize(
    ("ask", "member_id", "snapshot"),
    [
        pytest.param(ACQUIRE_RB, ASKER_MEMBER_ID, None, id="acquire"),
        # Member 17 has the league's biggest hole at WR, so it would head this
        # list on need alone if being out of the league did not remove it.
        pytest.param(MOVE_WR, SELLER_MEMBER_ID, None, id="move"),
        pytest.param(ACQUIRE_RB, ASKER_MEMBER_ID, DARK, id="below-the-coverage-gate"),
    ],
)
def test_eliminated_teams_are_never_counterparties(ask, member_id, snapshot) -> None:
    _, candidates = _generate(ask, member_id, snapshot=snapshot, limit=50)
    assert candidates
    assert all(c.counterparty_member_id != ELIMINATED_MEMBER_ID for c in candidates)
    assert all(c.counterparty != ELIMINATED for c in candidates)


def test_an_eliminated_manager_gets_no_advice_either() -> None:
    _, candidates = _generate(MOVE_WR, ELIMINATED_MEMBER_ID)
    assert candidates == []


@pytest.mark.parametrize(
    ("ask", "member_id", "label"),
    [
        pytest.param(ACQUIRE_RB, ASKER_MEMBER_ID, ASKER, id="acquire"),
        pytest.param(MOVE_WR, SELLER_MEMBER_ID, SELLER, id="move"),
        pytest.param(RENT_RB, ASKER_MEMBER_ID, ASKER, id="rental"),
    ],
)
def test_every_leg_moves_a_real_rostered_player_in_the_right_direction(
    ask, member_id, label
) -> None:
    snapshot, candidates = _generate(ask, member_id)
    held = {h.sleeper_player_id for t in snapshot.teams for h in t.holdings}
    assert candidates
    for candidate in candidates:
        for leg in candidate.asker_receives:
            assert leg.to_member == label and leg.from_member == candidate.counterparty
            assert leg.kind != "player" or leg.player_id in held
        for leg in candidate.asker_sends:
            assert leg.from_member == label and leg.to_member == candidate.counterparty
            assert leg.kind != "player" or leg.player_id in held


@pytest.mark.parametrize(
    ("ask", "member_id"),
    [
        pytest.param(ACQUIRE_RB, ASKER_MEMBER_ID, id="acquire"),
        pytest.param(MOVE_WR, SELLER_MEMBER_ID, id="move"),
        pytest.param(RENT_RB, ASKER_MEMBER_ID, id="rental"),
    ],
)
def test_only_players_and_faab_ever_change_hands(ask, member_id) -> None:
    """No money, no draft dollars: the Advisor may only propose what it can price."""
    _, candidates = _generate(ask, member_id)
    assert candidates
    kinds = {leg.kind for c in candidates for leg in c.asker_receives + c.asker_sends}
    assert kinds == {"player", "faab"}


def test_an_acquire_ask_only_brings_back_the_asked_position() -> None:
    _, candidates = _generate(ACQUIRE_RB)
    incoming = {
        leg.position for c in candidates for leg in c.asker_receives if leg.kind == "player"
    }
    assert incoming == {"RB"}
    assert not any(leg.kind == "player" for c in candidates for leg in c.asker_sends)


def test_a_move_ask_sends_the_asked_position_away() -> None:
    _, candidates = _generate(MOVE_WR, SELLER_MEMBER_ID)
    outgoing = {
        leg.position for c in candidates for leg in c.asker_sends if leg.kind == "player"
    }
    assert outgoing == {"WR"}
    assert not any(leg.kind == "player" for c in candidates for leg in c.asker_receives)


def test_an_either_ask_is_the_union_of_both_directions() -> None:
    """Member 9 is short a back and long a receiver, so "either" is both lists merged."""
    wide = {"limit": 50}
    _, acquire = _generate(Ask((), "acquire", None, False, (), False), TWO_WAY_MEMBER_ID, **wide)
    _, move = _generate(Ask((), "move", None, False, (), False), TWO_WAY_MEMBER_ID, **wide)
    _, either = _generate(Ask((), "either", None, False, (), False), TWO_WAY_MEMBER_ID, **wide)
    assert acquire and move
    merged = sorted(c.sort_key for c in acquire + move)
    assert [c.sort_key for c in either] == merged


def test_a_direction_the_asker_cannot_serve_contributes_nothing() -> None:
    """Member 18 has nothing above replacement, so "either" is its acquire list exactly."""
    _, acquire = _generate(ACQUIRE_RB)
    _, move = _generate(Ask(("RB",), "move", None, False, (), False))
    _, either = _generate(EITHER_RB)
    assert move == []
    assert [c.sort_key for c in either] == [c.sort_key for c in acquire]


def test_a_rental_carries_an_explicit_return_condition() -> None:
    snapshot, candidates = _generate(RENT_RB)
    assert candidates and all(c.structure == "rental" for c in candidates)
    for candidate in candidates:
        assert candidate.return_week == RENTAL_RETURN_WEEK
        assert candidate.return_condition == RENTAL_CONDITION
    assert snapshot.week + RENT_RB.horizon_weeks + 1 == RENTAL_RETURN_WEEK


def test_a_permanent_ask_carries_no_return_condition() -> None:
    _, candidates = _generate(ACQUIRE_RB)
    assert candidates and all(c.structure == "permanent" for c in candidates)
    assert all(c.return_condition is None and c.return_week is None for c in candidates)


def test_faab_never_exceeds_the_senders_remaining_budget() -> None:
    snapshot, candidates = _generate(ACQUIRE_RB)
    asker = snapshot.team_for_member(ASKER_MEMBER_ID)
    assert candidates
    for candidate in candidates:
        assert candidate.faab_total(ASKER) <= asker.faab_remaining
        assert candidate.faab_total(ASKER) >= FAAB_FLOOR
        assert all(
            leg.amount is None or leg.amount > 0
            for leg in candidate.asker_sends + candidate.asker_receives
        )


def test_on_a_move_the_counterparty_pays_from_its_own_budget() -> None:
    snapshot, candidates = _generate(MOVE_WR, SELLER_MEMBER_ID)
    assert candidates
    for candidate in candidates:
        buyer = snapshot.team_for_member(candidate.counterparty_member_id)
        assert candidate.faab_total(candidate.counterparty) <= buyer.faab_remaining
        assert candidate.faab_total(SELLER) == 0


def test_no_single_counterparty_can_fill_the_whole_list() -> None:
    """A deep roster gets two offers, not one per spare player it happens to hold.

    Below the gate a surplus is every bench body at the position, and four of the
    fixture's teams carry three spare running backs each. Without the per-team
    cap the first of them would take a quarter of the prompt on its own and the
    other sixteen managers would never be mentioned.
    """
    _, candidates = _generate(ACQUIRE_RB, snapshot=DARK, limit=50)
    deepest = max(
        len([h for h in team.bench() if h.position == "RB"]) for team in DARK.teams
    )
    assert deepest > OFFERS_PER_COUNTERPARTY
    counts = Counter(c.counterparty_member_id for c in candidates)
    assert counts and max(counts.values()) == OFFERS_PER_COUNTERPARTY


def test_a_named_counterparty_narrows_the_field() -> None:
    _, candidates = _generate(NAMED_SELLER)
    assert candidates and {c.counterparty for c in candidates} == {SELLER}
    assert len(candidates) <= OFFERS_PER_COUNTERPARTY


def test_a_comparable_price_sets_the_faab_when_history_has_one() -> None:
    _, candidates = _generate(ACQUIRE_RB, points=_priced_points())
    priced = [c for c in candidates if c.comparable_trade_code == COMPARABLE_CODE]
    assert priced and all(c.faab_total(ASKER) == COMPARABLE_FAAB for c in priced)
    assert all(c.reasons.price_basis == "comparable" for c in priced)
    assert all(c.reasons.price_faab == COMPARABLE_FAAB for c in priced)


def test_a_price_the_asker_cannot_pay_is_clamped_and_stops_quoting_history() -> None:
    """A precedent the buyer cannot afford is not a precedent this offer can cite."""
    snapshot = fixture_snapshot()
    budget = snapshot.team_for_member(ASKER_MEMBER_ID).faab_remaining
    assert budget < UNAFFORDABLE_FAAB
    _, candidates = _generate(ACQUIRE_RB, points=_priced_points(UNAFFORDABLE_FAAB))
    assert candidates
    for candidate in candidates:
        assert candidate.faab_total(ASKER) == budget
        assert candidate.comparable_trade_code is None
        assert candidate.reasons.price_basis == "default"


def test_a_sender_who_cannot_clear_the_floor_has_no_offer_to_make() -> None:
    snapshot = fixture_snapshot()
    broke = tuple(
        replace(team, faab_remaining=FAAB_FLOOR - 1)
        if team.member_id == ASKER_MEMBER_ID
        else team
        for team in snapshot.teams
    )
    _, candidates = _generate(ACQUIRE_RB, snapshot=replace(snapshot, teams=broke))
    assert candidates == []


def test_without_history_the_price_quotes_nothing() -> None:
    _, candidates = _generate(ACQUIRE_RB)
    assert candidates
    assert all(c.comparable_trade_code is None for c in candidates)
    assert all(c.reasons.price_basis == "default" for c in candidates)


@pytest.mark.parametrize(("ask", "member_id"), NO_TRADE)
def test_an_ask_no_honest_trade_answers_comes_back_empty(ask, member_id) -> None:
    _, candidates = _generate(ask, member_id)
    assert candidates == []


def test_the_limit_is_honoured() -> None:
    _, candidates = _generate(MOVE_WR, SELLER_MEMBER_ID, limit=3)
    _, full = _generate(MOVE_WR, SELLER_MEMBER_ID)
    assert len(candidates) == 3
    assert len(full) == MAX_CANDIDATES
    assert [c.sort_key for c in candidates] == [c.sort_key for c in full[:3]]


def test_each_candidate_carries_the_reasons_the_model_must_not_invent() -> None:
    snapshot, candidates = _generate(ACQUIRE_RB)
    scores = score_league(snapshot)
    asker = scores[ASKER_MEMBER_ID]
    assert candidates
    for candidate in candidates:
        reasons = candidate.reasons
        other = scores[candidate.counterparty_member_id]
        assert reasons.position == "RB"
        # The need being filled is the asker's, because the asker is buying.
        assert reasons.need_points == asker.needs["RB"] > Decimal(0)
        assert reasons.surplus_over_replacement > Decimal(0)
        assert reasons.counterparty_pressure_rank == other.pressure_rank
        assert candidate.counterparty_pressure_rank == other.pressure_rank
        assert reasons.pressure_delta == asker.pressure_rank - other.pressure_rank
        assert reasons.price_faab == candidate.faab_total(ASKER)
        assert candidate.asker_delta is not None and candidate.asker_delta > Decimal(0)
        assert candidate.counterparty_delta == -candidate.asker_delta


def test_a_move_reports_the_counterpartys_need_not_the_askers() -> None:
    snapshot, candidates = _generate(MOVE_WR, SELLER_MEMBER_ID)
    scores = score_league(snapshot)
    assert candidates
    for candidate in candidates:
        other = scores[candidate.counterparty_member_id]
        assert candidate.reasons.need_points == other.needs["WR"] > Decimal(0)
        assert candidate.asker_delta < Decimal(0) < candidate.counterparty_delta


def test_a_rental_is_valued_over_the_weeks_it_covers() -> None:
    """A three-week rental is worth three weeks of the player, not one."""
    snapshot = fixture_snapshot(horizon_weeks=4)
    _, weekly = _generate(ACQUIRE_RB, snapshot=snapshot)
    _, rented = _generate(RENT_RB, snapshot=snapshot)
    by_player = {tuple(sorted(c.player_ids())): c for c in weekly}
    assert rented
    for candidate in rented:
        one_week = by_player[tuple(sorted(candidate.player_ids()))]
        assert candidate.asker_delta > one_week.asker_delta


def test_below_the_coverage_gate_nothing_quotes_a_withheld_projection() -> None:
    """The gate withholds the team numbers; the roster shape still has trades in it.

    ``keep_player_points`` is the shape the real snapshot has -- provisional
    team weeks over perfectly numeric player rows -- and a generator that reads
    those per-player numbers would walk straight around the gate.
    """
    _, candidates = _generate(ACQUIRE_RB, snapshot=DARK)
    assert candidates
    assert all(c.asker_delta is None and c.counterparty_delta is None for c in candidates)
    assert all(c.reasons.surplus_over_replacement is None for c in candidates)
    assert all(c.reasons.need_points == Decimal(0) for c in candidates)
    assert all(c.counterparty_pressure_rank is None for c in candidates)
    assert all(c.reasons.pressure_delta is None for c in candidates)
