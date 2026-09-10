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
    PERMANENT_CODE,
    PERMANENT_FAAB,
    PERMANENT_ROW,
    RENTAL_CODE,
    RENTAL_FAAB,
    RENTAL_ROW,
    fixture_snapshot,
    price_history,
    trade_row,
)
from ultimate_guillotine.advisor.candidates import (
    DEFAULT_PRICE_SHARE,
    FAAB_FLOOR,
    MAX_CANDIDATES,
    MAX_PER_COUNTERPARTY,
    NEED_RANK_WEIGHT,
    OFFERS_PER_COUNTERPARTY,
    PRESSURE_WEIGHT,
    _pressure_term,
    _rank_term,
    generate_candidates,
)
from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.scoring import LEAGUE_TEAMS, score_league
from ultimate_guillotine.advisor.state import LAST_REGULAR_WEEK

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
OPEN_EITHER = Ask((), "either", None, False, (), False)
#: "Lend me a back for the rest of the season", and a horizon far past the end
#: of it -- both must land on the same week.
RENT_RB_OPEN = Ask(("RB",), "acquire", None, True, (), False)
RENT_RB_OVERLONG = Ask(("RB",), "acquire", 20, True, (), False)

#: The rental horizon the fixture's week 6 and a three-week ask produce.
RENTAL_RETURN_WEEK = 10
RENTAL_CONDITION = "returns before the Week 10 lock"
#: A rental that runs to the end of the regular season is back the week *after*
#: the last week it covers, so week 18 is one the borrower still gets to start.
SEASON_END_RETURN_WEEK = LAST_REGULAR_WEEK + 1
SEASON_END_CONDITION = f"returns before the Week {SEASON_END_RETURN_WEEK} lock"

#: Remaining FAAB in the fixture is ``1000 - 40 * team`` and member 17 is out, so
#: the seventeen live budgets run 960, 920, ... 360, 280 and their median is the
#: ninth of them: 1000 - 40 * 9. A price with no history is a fifth of that.
MEDIAN_FAAB = 640
DEFAULT_PRICE = MEDIAN_FAAB // DEFAULT_PRICE_SHARE
#: A raised budget for member 16 that is still under the league median, so the
#: anchor itself does not move and only the *payer* got richer.
RICHER_BUDGET = 600

#: Member 18's best two running backs, from ``fixture._starter_points``:
#: ``22 - 0.6*18 - 1.3*slot`` with the ``team % 3`` tilt of -1 at RB, so slots 1
#: and 2 are 9.9 - 1 and 8.6 - 1. An incoming back is worth what it adds to that
#: pair and nothing more -- the second one is the starter it displaces.
ASKER_RB_STARTERS = (Decimal("8.90"), Decimal("7.60"))
#: The asker's second starting running back, and the one an arriving back
#: displaces. Blanking his projection is the incumbent case: he can no longer be
#: ranked into the lineup, so a generator that only guards the *moving* players
#: measures the newcomer against member 18's third-best back (3.80) and reports
#: 8.40 gained instead of 4.60.
ASKER_RB2_PLAYER_ID = "p18s2"
#: The whole acquire-RB list on the bare fixture, in order:
#: ``(counterparty, player, price)``. Member 18 is short a back and members 2, 1
#: and 5 are the only teams carrying one above replacement (10.50).
GOLDEN_ACQUIRE_RB = (
    (2, "p02b0", DEFAULT_PRICE),
    (1, "p01b0", DEFAULT_PRICE),
    (2, "p02b1", DEFAULT_PRICE),
    (5, "p05b0", DEFAULT_PRICE),
)
#: Each of those backs' week-6 projection, from ``fixture._bench_points``:
#: ``12 - 0.4*team - 0.9*index`` with the same tilt, at RB.
ACQUIRE_RB_PROJECTIONS = {
    "p02b0": Decimal("12.20"),
    "p01b0": Decimal("11.60"),
    "p02b1": Decimal("11.30"),
    "p05b0": Decimal("11.00"),
}

#: A single accepted trade: member 1 sold his spare running back -- ``p01b0``,
#: ``Bench 01-0`` -- for 80 FAAB. One player, one payment, so the price point is
#: the whole 80. Built in :mod:`tests.advisor.fixture`, because the prompt tests
#: price the same two trades.
COMPARABLE_CODE = PERMANENT_CODE
COMPARABLE_FAAB = PERMANENT_FAAB
#: More FAAB than any fixture team has left, so the price has to be clamped.
UNAFFORDABLE_FAAB = 500


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


def _blank(player_id, snapshot=None):
    """The fixture with one player's projections removed and nothing else changed.

    This is what a feed that has every other number but not this one looks
    like: the holding is still on the roster, still at his position, and still
    a man the manager would start -- there is simply no projection to rank him
    by.
    """
    snapshot = fixture_snapshot() if snapshot is None else snapshot
    teams = tuple(
        replace(
            team,
            holdings=tuple(
                replace(h, projected_points={}) if h.sleeper_player_id == player_id else h
                for h in team.holdings
            ),
        )
        for team in snapshot.teams
    )
    return replace(snapshot, teams=teams)


def _priced_points(faab=COMPARABLE_FAAB):
    """The league's history: one permanent sale of a running back, at ``faab``."""
    row = trade_row(code=COMPARABLE_CODE, faab=faab, player_id="p01b0", player_name="Bench 01-0")
    return price_history([row])


def _mixed_points():
    """Both populations at once: one permanent sale and one rental of a back.

    The two prices differ, so which one a candidate quotes says which population
    it was read out of rather than merely that it found something.
    """
    return price_history([PERMANENT_ROW, RENTAL_ROW])


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
    outgoing = {leg.position for c in candidates for leg in c.asker_sends if leg.kind == "player"}
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


@pytest.mark.parametrize(
    "ask",
    [
        pytest.param(RENT_RB_OPEN, id="for-the-rest-of-the-season"),
        pytest.param(RENT_RB_OVERLONG, id="a-horizon-past-the-end-of-it"),
    ],
)
def test_a_season_long_rental_returns_after_the_last_regular_week(ask) -> None:
    """Returning *at* week 18 would take the final regular week off the borrower.

    A rental is over the weeks before the return, so a player home before the
    week 18 lock never plays week 18 for the team that rented him -- which is
    not what "for the rest of the season" buys. Both an open-ended horizon and
    one that overshoots land on the week after the last one played.
    """
    _, candidates = _generate(ask)
    assert candidates
    for candidate in candidates:
        assert candidate.return_week == SEASON_END_RETURN_WEEK
        assert candidate.return_condition == SEASON_END_CONDITION


def test_a_season_long_rental_is_paid_for_through_the_final_regular_week() -> None:
    """Thirteen weeks of 4.60, not twelve.

    On a snapshot that carries every week from 6 to 18, the best offered back
    beats member 18's second starter by 4.60 in each of them and the fixture
    decays both by the same half point a week, so an open-ended rental is worth
    ``13 * 4.60``. A rental that returned at week 18 would be worth ``12 *
    4.60`` and would have quietly dropped the last week of the regular season.
    """
    snapshot = fixture_snapshot(horizon_weeks=20)
    weeks = LAST_REGULAR_WEEK - snapshot.week + 1
    assert snapshot.weeks[-1] == LAST_REGULAR_WEEK
    _, candidates = _generate(RENT_RB_OPEN, snapshot=snapshot)
    best = candidates[0]
    (player_id,) = best.player_ids()
    per_week = ACQUIRE_RB_PROJECTIONS[player_id] - ASKER_RB_STARTERS[1]
    assert best.asker_delta == per_week * weeks
    assert best.asker_delta == Decimal("4.60") * 13


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
    deepest = max(len([h for h in team.bench() if h.position == "RB"]) for team in DARK.teams)
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


def test_a_rental_ask_is_priced_off_the_rental_and_never_the_permanent_sale() -> None:
    """A loan is quoted at what the league has paid for loans.

    Both trades are on file at the same position and only the structure of the
    ask separates them, so the FAAB and the trade code together say which
    population the price came out of. Pricing a three-week loan off a permanent
    acquisition would quote 80 FAAB for something the league has only ever paid
    30 for.
    """
    _, candidates = _generate(RENT_RB, points=_mixed_points())

    assert candidates
    assert all(c.structure == "rental" for c in candidates)
    assert all(c.comparable_trade_code == RENTAL_CODE for c in candidates)
    assert all(c.faab_total(ASKER) == RENTAL_FAAB for c in candidates)
    assert all(c.reasons.price_basis == "comparable" for c in candidates)


def test_a_permanent_ask_is_priced_off_the_sale_with_the_rental_on_the_same_file() -> None:
    """The other half of the same rule: a rental never cheapens a real purchase."""
    _, candidates = _generate(ACQUIRE_RB, points=_mixed_points())

    assert candidates
    assert all(c.structure == "permanent" for c in candidates)
    assert all(c.comparable_trade_code == COMPARABLE_CODE for c in candidates)
    assert all(c.faab_total(ASKER) == COMPARABLE_FAAB for c in candidates)


def test_a_rental_with_no_rental_history_falls_back_to_the_default_price() -> None:
    """An empty population is priced like an empty one: the league median.

    The permanent sale on file is not a rental comparable and not a rental
    median either, so filtering it out has to leave the default standing rather
    than leave the candidate unpriced -- there is always a price to offer.
    """
    _, candidates = _generate(RENT_RB, points=_priced_points())

    assert candidates
    assert all(c.comparable_trade_code is None for c in candidates)
    assert all(c.reasons.price_basis == "default" for c in candidates)
    assert all(c.reasons.price_faab == DEFAULT_PRICE for c in candidates)
    assert all(c.faab_total(ASKER) == DEFAULT_PRICE for c in candidates)


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
        replace(team, faab_remaining=FAAB_FLOOR - 1) if team.member_id == ASKER_MEMBER_ID else team
        for team in snapshot.teams
    )
    _, candidates = _generate(ACQUIRE_RB, snapshot=replace(snapshot, teams=broke))
    assert candidates == []


def test_without_history_the_price_quotes_nothing() -> None:
    _, candidates = _generate(ACQUIRE_RB)
    assert candidates
    assert all(c.comparable_trade_code is None for c in candidates)
    assert all(c.reasons.price_basis == "default" for c in candidates)
    assert all(c.reasons.price_faab == DEFAULT_PRICE for c in candidates)


def test_the_default_price_is_the_leagues_median_budget_not_the_payers() -> None:
    """The same player costs the same whoever is buying him.

    A default that scaled with the payer quoted 56 FAAB to the poorest team and
    112 to the richest for the identical back, and on a ``move`` it ranked the
    richest counterparty first for no reason but its bank balance. So member 18
    is made twice as rich and nothing about the answer moves: same price, same
    fit, same order.
    """
    snapshot = fixture_snapshot()
    asker = snapshot.team_for_member(ASKER_MEMBER_ID)
    richer = replace(
        snapshot,
        teams=tuple(
            replace(team, faab_remaining=asker.faab_remaining * 2)
            if team.member_id == ASKER_MEMBER_ID
            else team
            for team in snapshot.teams
        ),
    )
    _, poor = _generate(ACQUIRE_RB, snapshot=snapshot)
    _, rich = _generate(ACQUIRE_RB, snapshot=richer)
    assert poor and [c.sort_key for c in rich] == [c.sort_key for c in poor]
    assert {c.reasons.price_faab for c in poor + rich} == {DEFAULT_PRICE}


def test_a_richer_buyer_does_not_outrank_an_equal_offer_on_a_move() -> None:
    """The counterparty pays on a ``move``, so this is where money could buy rank.

    Member 16 goes from 360 FAAB to 600. Both are below the league's median of
    640, so the anchor every price is struck from does not move, and both are
    far above the 128 that price is -- so nothing is clamped either. The offers
    that sell member 16 a receiver come back at the identical price and the
    identical fit, in the identical place in the list.
    """
    snapshot = fixture_snapshot()
    buyer_id = 16
    buyer = snapshot.team_for_member(buyer_id)
    richer = replace(
        snapshot,
        teams=tuple(
            replace(team, faab_remaining=RICHER_BUDGET) if team.member_id == buyer_id else team
            for team in snapshot.teams
        ),
    )
    _, poor = _generate(MOVE_WR, SELLER_MEMBER_ID, snapshot=snapshot, limit=50)
    _, rich = _generate(MOVE_WR, SELLER_MEMBER_ID, snapshot=richer, limit=50)
    assert DEFAULT_PRICE < buyer.faab_remaining < RICHER_BUDGET < MEDIAN_FAAB
    assert [c.sort_key for c in rich] == [c.sort_key for c in poor]
    for before, after in zip(poor, rich, strict=True):
        assert before.reasons.price_faab == after.reasons.price_faab == DEFAULT_PRICE
        assert before.fit_score == after.fit_score


def test_the_acquire_list_is_exactly_this_sequence() -> None:
    """The golden list: who, which player, at what price, in what order.

    Every other test here checks one property; this one pins the whole answer,
    so a change in any of the arithmetic that feeds it has to be looked at
    rather than absorbed.
    """
    _, candidates = _generate(ACQUIRE_RB, limit=50)
    actual = tuple(
        (c.counterparty_member_id, min(c.player_ids()), c.reasons.price_faab) for c in candidates
    )
    assert actual == GOLDEN_ACQUIRE_RB


def test_no_counterparty_takes_more_than_its_share_of_the_whole_list() -> None:
    """The cap is on the finished list, not on one position and one direction.

    An open ask below the coverage gate crosses four positions and both
    directions, and member 1 alone can answer it eleven times -- more than a
    whole prompt's worth from one manager. The cap keeps four of them.
    """
    _, candidates = _generate(OPEN_EITHER, snapshot=DARK, limit=200)
    counts = Counter(c.counterparty_member_id for c in candidates)
    crowded = counts.most_common(1)[0][0]
    offered = 0
    for position in ("QB", "RB", "WR", "TE"):
        for direction in ("acquire", "move"):
            one_ask = Ask((position,), direction, None, False, (), False)
            _, narrow = _generate(one_ask, snapshot=DARK, limit=200)
            offered += sum(1 for c in narrow if c.counterparty_member_id == crowded)
    assert offered > MAX_PER_COUNTERPARTY
    assert max(counts.values()) == MAX_PER_COUNTERPARTY


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
        assert reasons.delta_basis == "lineup"


def test_a_move_reports_the_counterpartys_need_not_the_askers() -> None:
    snapshot, candidates = _generate(MOVE_WR, SELLER_MEMBER_ID)
    scores = score_league(snapshot)
    assert candidates
    for candidate in candidates:
        other = scores[candidate.counterparty_member_id]
        assert candidate.reasons.need_points == other.needs["WR"] > Decimal(0)
        # Member 3 sells a receiver it never started, so it loses nothing; the
        # buyer gains whatever the man improves *its* lineup by, if anything.
        assert candidate.asker_delta == Decimal(0) <= candidate.counterparty_delta


def test_a_delta_is_the_change_in_the_best_starting_lineup_not_the_gross_points() -> None:
    """What a back is worth is what he adds, which is his margin over the RB2.

    Member 18 starts 8.90 and 7.60 at running back. Every offered back beats
    7.60, so each one displaces it and is worth exactly ``projection - 7.60``:
    12.20 in is 4.60 gained, 11.60 is 4.00, 11.30 is 3.70, 11.00 is 3.40. The
    gross projection -- which is what a zero-sum delta reported -- is three
    times those numbers and describes a trade nobody would make.
    """
    _, candidates = _generate(ACQUIRE_RB)
    displaced = ASKER_RB_STARTERS[1]
    assert candidates
    for candidate in candidates:
        (player_id,) = candidate.player_ids()
        projection = ACQUIRE_RB_PROJECTIONS[player_id]
        assert candidate.asker_delta == projection - displaced
        assert candidate.asker_delta < projection


def test_an_unprojected_incumbent_makes_the_delta_unknown_rather_than_bigger() -> None:
    """A man with no number is not a man worth no points.

    Member 18's second starting back projects 7.60 and is what every offered
    back displaces. Blank him and he can no longer be ranked into a lineup, so
    the slot he held looks empty: the newcomer is measured against member 18's
    third back, 3.80, and the 4.60 upgrade is reported as 8.40 -- nearly double,
    from a missing number rather than a better trade. The asker's side is
    therefore unknown, and says so.

    The counterparty's side is untouched, because it is computed against member
    2's own fully projected roster -- one missing projection does not blank
    everything the trade knows. Nor does it drop the candidate: ``fit_score``
    never read the deltas, so the same four offers come back in the same order
    at the same price.
    """
    snapshot = _blank(ASKER_RB2_PLAYER_ID)
    _, candidates = _generate(ACQUIRE_RB, snapshot=snapshot)
    assert candidates
    for candidate in candidates:
        assert candidate.asker_delta is None
        assert candidate.reasons.delta_basis == "incomplete"
        # The seller's own back-up is still fully projected, so its side stands.
        assert candidate.counterparty_delta == Decimal(0)
    listed = [
        (c.counterparty_member_id, min(c.player_ids()), c.reasons.price_faab) for c in candidates
    ]
    assert listed == list(GOLDEN_ACQUIRE_RB)


def test_a_blanked_incumbent_only_darkens_the_position_the_trade_touches() -> None:
    """Every other position cancels in the diff, so it cannot make a delta unknown.

    Member 18's tight end has nothing to do with buying a running back: the same
    tight end starts before and after, so both lineups count him identically and
    a guard that blanked the whole roster would be refusing to answer a question
    it can answer.
    """
    tight_end = next(
        h.sleeper_player_id
        for h in fixture_snapshot().team_for_member(ASKER_MEMBER_ID).holdings
        if h.position == "TE"
    )
    _, candidates = _generate(ACQUIRE_RB, snapshot=_blank(tight_end))
    assert candidates
    for candidate in candidates:
        projection = ACQUIRE_RB_PROJECTIONS[min(candidate.player_ids())]
        assert candidate.asker_delta == projection - ASKER_RB_STARTERS[1]
        assert candidate.reasons.delta_basis == "lineup"


def test_a_bench_player_the_seller_never_started_costs_the_seller_nothing() -> None:
    """The two sides are independent numbers, and a trade is not zero-sum.

    Member 2 starts 20.50 and 19.20 at running back and is offering a 12.20
    bench back; taking him away leaves the same two starters, so the sale costs
    member 2 nothing at all while it is worth 4.60 to member 18.
    """
    _, candidates = _generate(ACQUIRE_RB)
    assert candidates
    for candidate in candidates:
        assert candidate.counterparty_delta == Decimal(0)
        assert candidate.asker_delta > Decimal(0)
        assert candidate.counterparty_delta != -candidate.asker_delta


def test_a_sale_is_worth_what_it_does_to_the_buyers_lineup() -> None:
    """Member 3's spare receiver, 10.90, against member 18's 8.30 and 7.00.

    He displaces the 7.00, so the sale is worth 3.90 to member 18 -- and 0.00
    to member 3, whose own receivers are 17.30 and 16.00 either way.
    """
    _, candidates = _generate(MOVE_WR, SELLER_MEMBER_ID, limit=50)
    to_asker = [c for c in candidates if c.counterparty_member_id == ASKER_MEMBER_ID]
    best = min(to_asker, key=lambda c: sorted(c.player_ids()))
    assert sorted(best.player_ids()) == ["p03b1"]
    assert best.counterparty_delta == Decimal("3.90")
    assert best.asker_delta == Decimal(0)


def test_a_rank_nudge_can_break_a_tie_but_never_beat_a_point() -> None:
    """Every nudge is normalised to its own weight, and the two stay under a point.

    An un-normalised ``weight * rank`` ran to eighteen times its weight and the
    pair of them spanned 3.6 points, which is more than most players differ by:
    the ranking was decided by who was easiest to ask rather than by what the
    roster gained.
    """
    ranks = [*range(1, LEAGUE_TEAMS + 1), None]
    biggest = max(
        _rank_term(rank, neediest_first=first) for rank in ranks for first in (True, False)
    )
    calmest = max(
        _pressure_term(rank, desperate_first=first) for rank in ranks for first in (True, False)
    )
    assert biggest == NEED_RANK_WEIGHT
    assert calmest == PRESSURE_WEIGHT
    assert biggest + calmest < Decimal(1)

    # And end to end: one position, one price, so everything the fit knows
    # besides the player's own margin is a nudge -- and the list is ordered by
    # the margins, whose spread is wider than a point.
    _, candidates = _generate(ACQUIRE_RB)
    margins = [c.reasons.surplus_over_replacement for c in candidates]
    nudges = [c.fit_score - c.reasons.surplus_over_replacement for c in candidates]
    assert max(nudges) - min(nudges) <= biggest + calmest
    assert max(margins) - min(margins) >= Decimal(1)
    assert margins == sorted(margins, reverse=True)


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
    assert all(c.reasons.delta_basis == "withheld" for c in candidates)
