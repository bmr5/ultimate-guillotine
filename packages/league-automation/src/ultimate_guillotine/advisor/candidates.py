"""Every trade the Advisor is allowed to suggest, built before the model runs.

This is the module that makes the spec's central promise keepable: "creative is
allowed, invented is not". The single model call receives this list and may only
rank it, discard from it, and write prose about it. A player, a member or an
amount that is not here cannot appear in an answer, because validation compares
the answer back against exactly these objects.

Generation is a cross product with three cuts. The asker's surplus is offered to
every other team's need, every other team's surplus is offered against the
asker's need, and then the rules apply: no eliminated team on either side of the
table, no leg that is not a player or FAAB, and no FAAB above what the sender
actually has left. Whatever survives is scored, sorted and capped, all
deterministically -- the same snapshot always yields the same list in the same
order, which is what lets a disputed answer be reproduced rather than argued
about.

**Nothing here is keyed on who is asking.** :func:`generate_candidates` reads
the asker's :class:`~ultimate_guillotine.advisor.scoring.TeamScore` out of the
same mapping every other team's comes from, and every threshold it applies is a
module constant. There is nowhere to put a per-member exception, which is how
the spec's fairness rule is enforced rather than merely intended.

**A candidate carries its own reasons.** :class:`CandidateReasons` records the
need being filled, how far above replacement the moved player is, where the
counterparty sits on the guillotine, and what the price is anchored to. The
model is handed conclusions, not raw rosters to re-derive them from, so there is
nothing left for it to invent and every clause of the eventual answer can be
traced to a number computed here.

**Only players and FAAB.** Dollars and draft dollars are things the league has
really traded, and
:mod:`~ultimate_guillotine.advisor.pricing` records them, but the Advisor never
proposes one: a suggestion it cannot price against the league's own history is a
suggestion it cannot defend.

**Below the coverage gate the shape of a roster is still true even though the
numbers are withheld.** Needs go to zero, pressure goes unranked and surpluses
fall back to counting bodies -- so candidates are still generated, but every
field that would quote a projection comes back ``None`` rather than reading the
per-player rows the team-level gate just withheld. That is the leak
:mod:`~ultimate_guillotine.advisor.scoring` warns about, and it is closed here by
gating on ``TeamScore.projections_known`` and on nothing else.

Every number is a :class:`~decimal.Decimal`, matching what the data layer hands
back for a ``numeric`` column. FAAB is an ``int``, because a bid is a whole
number of dollars and a fractional one is not a thing anybody could offer.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.pricing import PricePoint, comparables_for, median_faab
from ultimate_guillotine.advisor.scoring import (
    LEAGUE_TEAMS,
    NO_POINTS,
    POSITIONS,
    TeamScore,
    need_ranks,
    replacement_levels,
)
from ultimate_guillotine.advisor.state import (
    LAST_REGULAR_WEEK,
    AdvisorHolding,
    LeagueSnapshot,
)

#: How many candidates reach the prompt. The cap keeps the prompt bounded, which
#: the spec requires; twelve is three times the largest answer the schema allows,
#: so the model has real choices to discard rather than a list it must accept.
MAX_CANDIDATES = 12
#: How many of one counterparty's spare players at one position get offered. Two
#: is enough to show the model that the team has depth without letting a single
#: deep roster fill the whole list and crowd out the other sixteen teams.
OFFERS_PER_COUNTERPARTY = 2
#: No proposal offers a token amount of FAAB; below this it is not a sweetener,
#: and a sender who cannot clear it has no offer to make at all.
FAAB_FLOOR = 5
#: The share of the payer's budget a price defaults to when the league has never
#: traded the position: a fifth is enough to be a real offer and small enough
#: that a bad guess is not ruinous.
DEFAULT_PRICE_SHARE = 5

#: What a rental says out loud. Built from the horizon the ask parsed, so the
#: week in the sentence is the week the arithmetic used.
RETURN_TEMPLATE = "returns before the Week {week} lock"

#: Fit is mostly measured in projected points, and these are the small nudges
#: that order two otherwise identical offers. Each is deliberately an order of
#: magnitude below a point, so a rank can break a tie but never overturn a real
#: difference in what a roster gains.
NEED_RANK_WEIGHT = Decimal("0.1")
PRESSURE_WEIGHT = Decimal("0.1")
#: What a dollar of FAAB costs the fit. A hundred FAAB is worth half a point of
#: ordering, which is enough to prefer the cheaper of two equal players and not
#: enough to prefer a worse one.
PRICE_WEIGHT = Decimal("0.005")
#: Points arrive quantized to cents; :data:`PRICE_WEIGHT` is the one term that
#: can produce a third place, so the fit quantizes to three.
FIT_PRECISION = Decimal("0.001")

#: Where a price came from. ``comparable`` quotes one trade by code, ``median``
#: quotes the league's typical price at the position, and ``default`` quotes
#: nothing -- either the league has no history at the position, or the payer's
#: budget clamped the number so it is no longer the price anybody paid.
PriceBasis = Literal["comparable", "median", "default"]

__all__ = [
    "DEFAULT_PRICE_SHARE",
    "FAAB_FLOOR",
    "FIT_PRECISION",
    "MAX_CANDIDATES",
    "NEED_RANK_WEIGHT",
    "OFFERS_PER_COUNTERPARTY",
    "PRESSURE_WEIGHT",
    "PRICE_WEIGHT",
    "RETURN_TEMPLATE",
    "Candidate",
    "CandidateLeg",
    "CandidateReasons",
    "PriceBasis",
    "generate_candidates",
]


@dataclass(frozen=True)
class CandidateLeg:
    """One thing moving one way. A player or FAAB, and nothing else.

    ``from_member`` and ``to_member`` are ``member_label`` -- the league's one
    public label for a member, the string that gets rendered. The join key
    ``display_name`` is deliberately never carried here, so it cannot be
    printed from a leg.
    """

    kind: Literal["player", "faab"]
    player_id: str | None
    player_name: str | None
    position: str | None
    amount: int | None
    from_member: str
    to_member: str


@dataclass(frozen=True)
class CandidateReasons:
    """Why this trade is on the list, in numbers the model may quote but not compute.

    Every field is either a figure produced by
    :mod:`~ultimate_guillotine.advisor.scoring` or a price produced by
    :mod:`~ultimate_guillotine.advisor.pricing`. ``None`` means "withheld or
    unknown", never zero: below the coverage gate the projections behind
    ``surplus_over_replacement`` and ``pressure_delta`` may not be shown, and an
    eliminated or unranked team has no pressure rank to subtract.
    """

    #: The position the trade is about.
    position: str
    #: How far below the league's median starters the *receiving* side is at
    #: that position -- the asker on an acquire, the counterparty on a move.
    need_points: Decimal
    #: The receiving side's 1-based rank at that position, neediest first.
    need_rank: int | None
    #: How far the moved player projects above a free replacement.
    surplus_over_replacement: Decimal | None
    #: The counterparty's distance from the guillotine, 1 being closest.
    counterparty_pressure_rank: int | None
    #: Asker rank minus counterparty rank. Positive means the counterparty is
    #: further from the cut line than the asker, and so is the calmer party.
    pressure_delta: int | None
    #: The FAAB in the offer, and what set it.
    price_faab: int
    price_basis: PriceBasis
    comparable_trade_code: str | None


@dataclass(frozen=True)
class Candidate:
    """One concrete, priced, legal proposal.

    ``asker_receives`` and ``asker_sends`` are written from the asker's point of
    view because that is whose question is being answered; every leg still names
    both ends, so nothing downstream has to remember which list it is reading.
    """

    counterparty: str
    counterparty_member_id: int
    counterparty_team_id: int
    asker_receives: tuple[CandidateLeg, ...]
    asker_sends: tuple[CandidateLeg, ...]
    structure: Literal["permanent", "rental"]
    return_week: int | None
    return_condition: str | None
    fit_score: Decimal
    asker_delta: Decimal | None
    counterparty_delta: Decimal | None
    comparable_trade_code: str | None
    counterparty_pressure_rank: int | None
    reasons: CandidateReasons

    def player_ids(self) -> frozenset[str]:
        return frozenset(
            leg.player_id
            for leg in self.asker_receives + self.asker_sends
            if leg.player_id is not None
        )

    def faab_total(self, sender: str) -> int:
        """How much FAAB this member pays under this proposal."""
        return sum(
            leg.amount or 0
            for leg in self.asker_receives + self.asker_sends
            if leg.kind == "faab" and leg.from_member == sender
        )

    @property
    def sort_key(self) -> tuple[Decimal, int, tuple[str, ...], int]:
        """Best fit first, then a total order that no two candidates can share.

        Fit decides, and where two candidates fit equally well the counterparty's
        team id decides, then the players, then the price. A sort that stopped at
        the fit score would leave equal-fitting offers in whatever order the
        roster query happened to return them, and the same question would get
        two different answers on two different days.
        """
        return (
            -self.fit_score,
            self.counterparty_team_id,
            tuple(sorted(self.player_ids())),
            sum(leg.amount or 0 for leg in self.asker_receives + self.asker_sends),
        )


def _leg_player(holding: AdvisorHolding, sender: str, receiver: str) -> CandidateLeg:
    return CandidateLeg(
        kind="player",
        player_id=holding.sleeper_player_id,
        player_name=holding.player_name,
        position=holding.position,
        amount=None,
        from_member=sender,
        to_member=receiver,
    )


def _leg_faab(amount: int, sender: str, receiver: str) -> CandidateLeg:
    return CandidateLeg(
        kind="faab",
        player_id=None,
        player_name=None,
        position=None,
        amount=amount,
        from_member=sender,
        to_member=receiver,
    )


def _price(
    points: Sequence[PricePoint], position: str, budget: int
) -> tuple[int, PriceBasis, str | None] | None:
    """What this position has cost, clamped to what the buyer actually has.

    The trade code comes back only when a real comparable set the number and the
    buyer can pay it in full, so nothing ever quotes a precedent it then had to
    round down: a clamped price is the Advisor's own guess and says so. A buyer
    who cannot clear :data:`FAAB_FLOOR` has no offer to make, and ``None`` here
    drops the candidate rather than proposing a token amount.
    """
    if budget < FAAB_FLOOR:
        return None
    comparables = comparables_for(points, position, limit=1)
    if comparables:
        asked, basis, code = comparables[0].faab or 0, "comparable", comparables[0].trade_code
    else:
        typical = median_faab(points, position)
        if typical is not None:
            asked, basis, code = typical, "median", None
        else:
            asked, basis, code = budget // DEFAULT_PRICE_SHARE, "default", None
    amount = max(FAAB_FLOOR, min(int(asked), budget))
    if amount != int(asked):
        return (amount, "default", None)
    return (amount, basis, code)


def _points_over(holding: AdvisorHolding, weeks: Sequence[int]) -> Decimal | None:
    """A holding's projection summed over the weeks a trade covers, or ``None``.

    One missing week makes the whole total unknown rather than smaller: a trade
    valued over three weeks of which the feed has two is not a two-week trade.
    """
    total = NO_POINTS
    for week in weeks:
        points = holding.projected_for(week)
        if points is None:
            return None
        total += points
    return total


def _delta(
    incoming: Sequence[AdvisorHolding],
    outgoing: Sequence[AdvisorHolding],
    weeks: Sequence[int],
    *,
    known: bool,
) -> Decimal | None:
    """Projected points gained over ``weeks``, or ``None`` when it may not be said.

    ``known`` is the coverage gate. Below it the per-player rows usually still
    carry numbers, and adding them up anyway would publish exactly what the
    team-level gate withheld.
    """
    if not known:
        return None
    gained = NO_POINTS
    for holding in incoming:
        points = _points_over(holding, weeks)
        if points is None:
            return None
        gained += points
    for holding in outgoing:
        points = _points_over(holding, weeks)
        if points is None:
            return None
        gained -= points
    return gained


def _covered_weeks(snapshot: LeagueSnapshot, ask: Ask) -> tuple[int, ...]:
    """The weeks a proposal is valued over: this one, or a rental's whole term.

    A permanent trade is judged on the current week, because that is the week
    the snapshot is anchored to and the only one every consumer agrees on. A
    rental is judged on the weeks it actually covers, capped at the horizon the
    snapshot was loaded with -- a week nobody read projections for cannot be
    added to a total.
    """
    if not ask.rental:
        return (snapshot.week,)
    last = _return_week(snapshot, ask)
    return tuple(w for w in snapshot.weeks if w < last) or (snapshot.week,)


def _return_week(snapshot: LeagueSnapshot, ask: Ask) -> int:
    """The week a borrowed player is back before the lock of.

    A rental covers the week it is agreed in plus ``horizon_weeks`` more, so a
    three-week rental struck in week 6 runs through week 9 and the player is
    home before week 10 locks. A rental with no bounded horizon -- "for the rest
    of the season" -- runs to the end of the regular season, which is also the
    cap every bounded one is clamped to.
    """
    if ask.horizon_weeks is None:
        return LAST_REGULAR_WEEK
    return min(snapshot.week + ask.horizon_weeks + 1, LAST_REGULAR_WEEK)


def _named_member_ids(snapshot: LeagueSnapshot, ask: Ask) -> frozenset[int] | None:
    """Member ids the ask named, or ``None`` when it named nobody.

    An empty frozenset is not the same as ``None``: it means every name in the
    ask failed to resolve -- misspelt, ambiguous, or a manager who is out -- and
    the honest answer to "trade with Casey" when Casey cannot be found is
    nothing, not a trade with somebody else.
    """
    if not ask.named_counterparties:
        return None
    resolved = {
        team.member_id
        for name in ask.named_counterparties
        if (team := snapshot.team_by_name(name)) is not None
    }
    return frozenset(resolved)


def _rank_term(rank: int | None, *, neediest_first: bool) -> Decimal:
    """Turn a 1-based rank into a small, bounded nudge.

    ``neediest_first`` is which end of the list the caller wants. Selling to the
    league's neediest team is the easy sale, so a move rewards rank 1; buying
    from the team that needs the position least is the easy buy, so an acquire
    rewards the far end. An unranked team -- eliminated, or below the gate --
    gets nothing either way rather than being sorted to a made-up position.
    """
    if rank is None:
        return NO_POINTS
    place = LEAGUE_TEAMS + 1 - rank if neediest_first else rank
    return NEED_RANK_WEIGHT * Decimal(place)


def _pressure_term(rank: int | None, *, desperate_first: bool) -> Decimal:
    """The same nudge, read off the guillotine rather than off a position.

    A team about to be cut wants points this week and will pay for them, so it
    is the willing *buyer* on a move. The same team is the last one that will
    sell you a starter, so an acquire looks for the calm end of the table.
    """
    if rank is None:
        return NO_POINTS
    place = LEAGUE_TEAMS + 1 - rank if desperate_first else rank
    return PRESSURE_WEIGHT * Decimal(place)


def _margin(
    holding: AdvisorHolding, position: str, replacement: Mapping[str, Decimal], *, known: bool
) -> Decimal | None:
    """How far the moved player projects above a free replacement, or ``None``.

    ``None`` below the coverage gate for the same reason as :func:`_delta`, and
    ``None`` when the league has no replacement level at the position -- an
    unknown margin is not a zero one.
    """
    if not known:
        return None
    line = replacement.get(position, NO_POINTS)
    points = holding.projected_now
    if points is None or line == NO_POINTS:
        return None
    return points - line


def _wants(score: TeamScore, position: str, *, known: bool) -> bool:
    """Does this team have a reason to take a player at this position?

    Above the gate a need of zero is a real answer: a team already at or above
    the league's median starters does not improve by adding another one, and
    proposing it anyway is how an advisor earns a reputation for noise. Below
    the gate every need is zero because none of them could be computed, so the
    question is unanswerable and the generator falls back to roster shape
    exactly as :func:`~ultimate_guillotine.advisor.scoring.team_surplus` does.
    """
    return not known or score.needs.get(position, NO_POINTS) > NO_POINTS


def _pressure_delta(asker: TeamScore, other: TeamScore) -> int | None:
    if asker.pressure_rank is None or other.pressure_rank is None:
        return None
    return asker.pressure_rank - other.pressure_rank


@dataclass(frozen=True)
class _Run:
    """Everything one call has already decided, computed once for the whole run.

    The replacement levels, the need ranks and the coverage gate are properties
    of the snapshot, and the structure and the covered weeks are properties of
    the ask. Recomputing any of them per counterparty would be both slower and a
    place for two candidates in one answer to disagree with each other.
    """

    points: Sequence[PricePoint]
    ranks: Mapping[str, Mapping[int, int | None]]
    replacement: Mapping[str, Decimal]
    weeks: tuple[int, ...]
    known: bool
    structure: Literal["permanent", "rental"]
    return_week: int | None
    return_condition: str | None


def generate_candidates(
    snapshot: LeagueSnapshot,
    scores: Mapping[int, TeamScore],
    asker_member_id: int,
    ask: Ask,
    points: Sequence[PricePoint],
    *,
    limit: int = MAX_CANDIDATES,
) -> list[Candidate]:
    """Cross the asker's roster against every legal counterparty's roster.

    Returns an empty list rather than a weak suggestion whenever no honest trade
    answers the ask: the asker is eliminated, the asker has nothing above
    replacement to send, nobody has what the asker needs, or every counterparty
    the ask named is one this function may not or cannot use. "There is nothing
    here" is an answer the Advisor is allowed to give, and it is a much better
    one than a trade nobody would make.
    """
    asker_team = snapshot.team_for_member(asker_member_id)
    asker = scores.get(asker_member_id)
    if asker_team is None or asker is None or asker.is_eliminated:
        return []

    return_week = _return_week(snapshot, ask) if ask.rental else None
    run = _Run(
        points=points,
        ranks={position: need_ranks(scores, position) for position in POSITIONS},
        replacement=replacement_levels(snapshot),
        weeks=_covered_weeks(snapshot, ask),
        known=asker.projections_known,
        structure="rental" if ask.rental else "permanent",
        return_week=return_week,
        return_condition=(
            None if return_week is None else RETURN_TEMPLATE.format(week=return_week)
        ),
    )
    wanted = tuple(p for p in (ask.positions or POSITIONS) if p in POSITIONS)
    named = _named_member_ids(snapshot, ask)

    candidates: list[Candidate] = []
    for team in snapshot.teams:
        if team.member_id == asker_member_id or team.is_eliminated:
            continue
        if named is not None and team.member_id not in named:
            continue
        other = scores.get(team.member_id)
        if other is None or other.is_eliminated:
            continue
        for position in wanted:
            if ask.direction != "move":
                candidates.extend(
                    _acquire(run, asker, other, position, asker_team.faab_remaining)
                )
            if ask.direction != "acquire":
                candidates.extend(_move(run, asker, other, position, team.faab_remaining))

    candidates.sort(key=lambda candidate: candidate.sort_key)
    return candidates[:limit]


def _build(
    run: _Run,
    asker: TeamScore,
    other: TeamScore,
    position: str,
    holding: AdvisorHolding,
    *,
    to_asker: bool,
    receiver: TeamScore,
    price: tuple[int, PriceBasis, str | None],
    fit_base: Decimal,
) -> Candidate:
    """Assemble one proposal once the direction has decided everything about it.

    ``to_asker`` is which way the player moves; the FAAB always moves the other
    way, because a candidate is one player against one price and never a swap.
    Both directions land here so that a field can never be filled in on an
    acquire and forgotten on a move.
    """
    amount, basis, code = price
    seller, buyer = (other, asker) if to_asker else (asker, other)
    player_leg = _leg_player(holding, seller.member_label, buyer.member_label)
    faab_leg = _leg_faab(amount, buyer.member_label, seller.member_label)
    delta = _delta(
        [holding] if to_asker else [], [] if to_asker else [holding], run.weeks, known=run.known
    )
    margin = _margin(holding, position, run.replacement, known=run.known)
    return Candidate(
        counterparty=other.member_label,
        counterparty_member_id=other.member_id,
        counterparty_team_id=other.team_id,
        asker_receives=(player_leg,) if to_asker else (faab_leg,),
        asker_sends=(faab_leg,) if to_asker else (player_leg,),
        structure=run.structure,
        return_week=run.return_week,
        return_condition=run.return_condition,
        fit_score=(fit_base + (margin or NO_POINTS)).quantize(FIT_PRECISION),
        asker_delta=delta,
        counterparty_delta=None if delta is None else -delta,
        comparable_trade_code=code,
        counterparty_pressure_rank=other.pressure_rank,
        reasons=CandidateReasons(
            position=position,
            need_points=receiver.needs.get(position, NO_POINTS),
            need_rank=run.ranks[position].get(receiver.member_id),
            surplus_over_replacement=margin,
            counterparty_pressure_rank=other.pressure_rank,
            pressure_delta=_pressure_delta(asker, other),
            price_faab=amount,
            price_basis=basis,
            comparable_trade_code=code,
        ),
    )


def _acquire(
    run: _Run, asker: TeamScore, other: TeamScore, position: str, budget: int
) -> list[Candidate]:
    """The asker buys one of the counterparty's spare players and pays in FAAB.

    The fit is the asker's own need, plus how far the player is above a free
    replacement, nudged toward the counterparty least likely to say no -- the
    team that needs the position least and sits furthest from the cut line --
    and docked for what the player costs.
    """
    if not _wants(asker, position, known=run.known):
        return []
    price = _price(run.points, position, budget)
    if price is None:
        return []
    fit_base = (
        asker.needs.get(position, NO_POINTS)
        + _rank_term(run.ranks[position].get(other.member_id), neediest_first=False)
        + _pressure_term(other.pressure_rank, desperate_first=False)
        - PRICE_WEIGHT * Decimal(price[0])
    )
    return [
        _build(
            run, asker, other, position, holding,
            to_asker=True, receiver=asker, price=price, fit_base=fit_base,
        )
        for holding in other.surpluses.get(position, ())[:OFFERS_PER_COUNTERPARTY]
    ]


def _move(
    run: _Run, asker: TeamScore, other: TeamScore, position: str, budget: int
) -> list[Candidate]:
    """The asker sells a spare player to a team that has a hole at that position.

    The mirror image, with both nudges reversed: the easiest sale is to the team
    with the biggest hole at the position and the least time left to fix it, and
    a bigger cheque makes the deal better rather than worse.
    """
    if not _wants(other, position, known=run.known):
        return []
    price = _price(run.points, position, budget)
    if price is None:
        return []
    fit_base = (
        other.needs.get(position, NO_POINTS)
        + _rank_term(run.ranks[position].get(other.member_id), neediest_first=True)
        + _pressure_term(other.pressure_rank, desperate_first=True)
        + PRICE_WEIGHT * Decimal(price[0])
    )
    return [
        _build(
            run, asker, other, position, holding,
            to_asker=False, receiver=other, price=price, fit_base=fit_base,
        )
        for holding in asker.surpluses.get(position, ())[:OFFERS_PER_COUNTERPARTY]
    ]
