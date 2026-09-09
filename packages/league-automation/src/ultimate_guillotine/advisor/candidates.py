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
from statistics import median
from typing import Literal

from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.pricing import (
    COMPARABLE_KINDS,
    PricePoint,
    comparables_for,
    median_faab,
)
from ultimate_guillotine.advisor.scoring import (
    LEAGUE_TEAMS,
    NO_POINTS,
    POINT_PRECISION,
    POSITIONS,
    STARTER_SLOTS,
    TeamScore,
    need_ranks,
    replacement_levels,
)
from ultimate_guillotine.advisor.state import (
    LAST_REGULAR_WEEK,
    AdvisorHolding,
    AdvisorTeamState,
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
#: How many candidates any one counterparty may contribute to the finished list,
#: whatever mixture of positions and directions they came from. An open ask
#: crosses four positions and both directions, so without this a single
#: well-stocked roster could supply sixteen offers and take the whole prompt;
#: a third of :data:`MAX_CANDIDATES` leaves room for at least three managers.
MAX_PER_COUNTERPARTY = 4
#: No proposal offers a token amount of FAAB; below this it is not a sweetener,
#: and a sender who cannot clear it has no offer to make at all.
FAAB_FLOOR = 5
#: The share of the *league's* median remaining budget a price defaults to when
#: the league has never traded the position: a fifth is enough to be a real
#: offer and small enough that a bad guess is not ruinous. The anchor is
#: league-wide on purpose -- a price that scaled with the payer would make the
#: same player cost 56 FAAB from a poor team and 112 from a rich one, and on a
#: ``move`` it would rank the richest counterparty first for no reason but its
#: bank balance. The payer's own budget is a clamp on the answer, never its base.
DEFAULT_PRICE_SHARE = 5

#: What a rental says out loud. Built from the horizon the ask parsed, so the
#: week in the sentence is the week the arithmetic used.
RETURN_TEMPLATE = "returns before the Week {week} lock"

#: Fit is measured in projected points, and these are the small nudges that
#: order two otherwise identical offers. Each is normalised to at most its own
#: weight -- see :func:`_rank_term` -- and the two together stay under a point,
#: so a rank can break a tie but can never overturn a one-point difference in
#: what a roster actually gains.
NEED_RANK_WEIGHT = Decimal("0.4")
PRESSURE_WEIGHT = Decimal("0.4")
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

#: Why a candidate's lineup deltas are what they are. ``lineup`` means both
#: sides were computed; ``withheld`` means the coverage gate refused to publish
#: the projections behind them; ``incomplete`` means a player who would have
#: competed for one of the affected starter slots -- one of the men moving, or
#: an incumbent already on the roster -- has no projection for one of the
#: covered weeks, so at least one side's delta is unknown rather than zero.
DeltaBasis = Literal["lineup", "withheld", "incomplete"]

__all__ = [
    "DEFAULT_PRICE_SHARE",
    "FAAB_FLOOR",
    "FIT_PRECISION",
    "MAX_CANDIDATES",
    "MAX_PER_COUNTERPARTY",
    "NEED_RANK_WEIGHT",
    "OFFERS_PER_COUNTERPARTY",
    "PRESSURE_WEIGHT",
    "PRICE_WEIGHT",
    "RETURN_TEMPLATE",
    "Candidate",
    "CandidateLeg",
    "CandidateReasons",
    "DeltaBasis",
    "PriceBasis",
    "generate_candidates",
    "span_text",
    "weeks_covered",
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
    #: Whether the two lineup deltas could be computed, and if not, why. Anything
    #: but ``lineup`` means at least one of them is ``None`` and the answer must
    #: say the change could not be computed rather than treat it as zero.
    delta_basis: DeltaBasis


@dataclass(frozen=True)
class Candidate:
    """One concrete, priced, legal proposal.

    ``asker_receives`` and ``asker_sends`` are written from the asker's point of
    view because that is whose question is being answered; every leg still names
    both ends, so nothing downstream has to remember which list it is reading.

    ``asker_delta`` and ``counterparty_delta`` are **not** negations of each
    other. Each is what the trade does to that side's own best starting lineup
    over the weeks it covers, and a trade both sides should make is one where
    both numbers are positive -- which is exactly what a gross-projection delta
    could never show, because it made every trade sum to zero.
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
    #: Change in the asker's best legal starting lineup, summed over the covered
    #: weeks. ``None`` below the coverage gate, and ``None`` when anybody who
    #: could have contested the slots the trade touches -- a moving player or an
    #: incumbent -- has no projection for one of those weeks;
    #: ``reasons.delta_basis`` says which. ``fit_score`` does not read either
    #: delta, so a candidate whose delta is unknown is still ranked, on the
    #: need, the margin over replacement, the rank nudges and the price.
    asker_delta: Decimal | None
    #: The same figure for the counterparty, computed against its own roster.
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


def weeks_covered(snapshot: LeagueSnapshot, candidate: Candidate) -> tuple[int, ...]:
    """The weeks a built candidate's point changes were summed over.

    The same arithmetic :func:`_covered_weeks` applied to the ask, read back off
    the finished candidate so that anything rendering one of its figures -- the
    facts block, the chat text -- names the span the number really covers: a
    permanent trade is judged on the snapshot's own week, and a rental on every
    loaded week before it returns.
    """
    if candidate.structure != "rental" or candidate.return_week is None:
        return (snapshot.week,)
    return tuple(w for w in snapshot.weeks if w < candidate.return_week) or (snapshot.week,)


def span_text(weeks: Sequence[int]) -> str:
    """``Week 6`` or ``Weeks 6–9`` -- which weeks a summed figure covers.

    A three-week rental's ``+12.00`` and a one-week trade's ``+12.00`` are not
    the same offer. Every point change is rendered beside its own span, and both
    come from here, so the number and the weeks behind it cannot drift apart in
    one consumer while staying right in the other.
    """
    if len(weeks) == 1:
        return f"Week {weeks[0]}"
    return f"Weeks {weeks[0]}–{weeks[-1]}"


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


def _median_budget(snapshot: LeagueSnapshot) -> int:
    """The league's median remaining FAAB, which every default price anchors to.

    Eliminated teams are left out for the same reason
    :func:`~ultimate_guillotine.advisor.scoring.league_medians` leaves them out:
    a manager who is no longer bidding is not part of the market that sets what
    things cost.
    """
    budgets = [t.faab_remaining for t in snapshot.teams if not t.is_eliminated]
    return int(median(budgets)) if budgets else 0


def _price(
    points: Sequence[PricePoint],
    position: str,
    budget: int,
    anchor: int,
    *,
    kinds: tuple[str, ...] = COMPARABLE_KINDS,
) -> tuple[int, PriceBasis, str | None] | None:
    """What this position has cost, clamped to what the buyer actually has.

    ``kinds`` is the population the price is read out of, and it is the ask's
    own structure: a rental is priced off what the league has paid to *borrow*
    that position, never off what it has paid to keep one. The comparable and
    the median come from the one population, so a rental with no rental history
    falls through to the league-median default rather than quoting a permanent
    acquisition at somebody who asked to borrow.

    ``anchor`` is the league's median remaining budget, and it is the *only*
    thing a price with no history is derived from. Deriving it from ``budget``
    instead would make the identical player cost whatever the buyer could
    afford, which is not a price at all: two managers asking the same question
    would be quoted different numbers, and on a ``move`` the fit would rank the
    richest counterparty first purely because the cheque it can write is bigger.

    ``budget`` therefore only ever *reduces* the answer. The trade code comes
    back only when a real comparable set the number and the buyer can pay it in
    full, so nothing quotes a precedent it then had to round down: a clamped
    price is the Advisor's own guess and says so. A buyer who cannot clear
    :data:`FAAB_FLOOR` has no offer to make, and ``None`` here drops the
    candidate rather than proposing a token amount.
    """
    if budget < FAAB_FLOOR:
        return None
    comparables = comparables_for(points, position, limit=1, kinds=kinds)
    if comparables:
        asked, basis, code = comparables[0].faab or 0, "comparable", comparables[0].trade_code
    else:
        typical = median_faab(points, position, kinds=kinds)
        if typical is not None:
            asked, basis, code = typical, "median", None
        else:
            asked, basis, code = anchor // DEFAULT_PRICE_SHARE, "default", None
    amount = max(FAAB_FLOOR, min(int(asked), budget))
    if amount != int(asked):
        return (amount, "default", None)
    return (amount, basis, code)


def _startable(team: AdvisorTeamState) -> tuple[AdvisorHolding, ...]:
    """The players a team may actually field. IR and taxi holdings are not among them."""
    return team.starters() + team.bench()


def _lineup_points(holdings: Sequence[AdvisorHolding], week: int) -> Decimal:
    """The best legal starting lineup this set of players can field in one week.

    Depth is :data:`~ultimate_guillotine.advisor.scoring.STARTER_SLOTS` -- one
    QB, two RBs, two WRs, one TE -- for exactly the reason
    :mod:`~ultimate_guillotine.advisor.scoring` gives: the FLEX is one slot that
    three positions may fill, so counting it at each of them would invent two
    starters per team that the league never fields. Because no FLEX slot is
    filled here, the only players who can compete for a slot are the ones at
    that position, which is what :func:`_contenders` relies on.

    A player nobody has projected for the week cannot be ranked and so cannot
    claim a slot. That silently shortens the lineup, and a shortened lineup is
    not a smaller one -- it is an unknown one -- so :func:`_lineup_delta`
    refuses to value any trade that touches a position where somebody is
    missing a number.
    """
    total = NO_POINTS
    for position in POSITIONS:
        slots = STARTER_SLOTS.get(position, 0)
        if not slots:
            continue
        projections = sorted(
            (
                projected
                for holding in holdings
                if holding.position == position
                and (projected := holding.projected_for(week)) is not None
            ),
            reverse=True,
        )
        total += sum(projections[:slots], NO_POINTS)
    return total


def _contenders(
    roster: Sequence[AdvisorHolding], moving: Sequence[AdvisorHolding]
) -> list[AdvisorHolding]:
    """Everybody whose projection the diff depends on.

    Only the positions the trade touches can change the total: at every other
    position the before and after lineups are the same players, so the two
    ``_lineup_points`` terms cancel exactly. At a touched position, though, the
    diff depends on the *whole* depth chart -- the incoming man is worth the
    margin over whoever he displaces, and who that is depends on every
    incumbent's number. A position with no starter slot cannot be displaced
    from and so is not touched at all.

    Flex eligibility does not widen this set, because :func:`_lineup_points`
    fills no FLEX slot; if it ever did, the flex-eligible incumbents at the
    affected slots would have to be counted here too.
    """
    affected = {
        holding.position
        for holding in moving
        if holding.position is not None and STARTER_SLOTS.get(holding.position, 0)
    }
    return list(moving) + [h for h in roster if h.position in affected]


def _lineup_delta(
    roster: Sequence[AdvisorHolding],
    incoming: Sequence[AdvisorHolding],
    outgoing: Sequence[AdvisorHolding],
    weeks: Sequence[int],
    *,
    known: bool,
) -> Decimal | None:
    """What these legs do to one side's best starting lineup, summed over ``weeks``.

    A player's gross projection is not what acquiring him is worth. A team that
    already starts two better running backs gains nothing by adding a third, and
    a team that gives up a bench player it was never going to start loses
    nothing by sending him -- so a bench-for-bench trade is worth roughly zero to
    both sides, and an upgrade is worth the margin over the starter it displaces
    and no more. Reading the gross projection instead made every trade
    perfectly zero-sum, which is precisely the shape a trade nobody should make
    has: both sides moved the same points, so neither side was ever shown a
    reason to say yes.

    The two sides are therefore computed independently, against their own
    rosters, and do not sum to zero. ``known`` is the coverage gate: below it
    the per-player rows usually still carry numbers, and adding them up anyway
    would publish exactly what the team-level gate withheld. One missing week on
    a player who is actually moving makes the whole total unknown rather than
    smaller -- a trade valued over three weeks of which the feed has two is not
    a two-week trade.

    The same is true of an *incumbent*. A roster player with no projection for a
    covered week cannot claim a starter slot in :func:`_lineup_points`, so the
    lineup he should have been in comes up a man short and the arriving player
    is credited with filling an empty slot rather than with beating him: on the
    test league, blanking the second running back turns a 4.60 upgrade into an
    8.40 one. Whoever could have contested the slots this trade touches --
    see :func:`_contenders` -- must therefore have a number for every covered
    week, or the delta is unknown too.
    """
    if not known:
        return None
    moving = list(incoming) + list(outgoing)
    contenders = _contenders(roster, moving)
    if any(h.projected_for(week) is None for h in contenders for week in weeks):
        return None
    leaving = {h.sleeper_player_id for h in outgoing}
    before = list(roster)
    after = [h for h in before if h.sleeper_player_id not in leaving] + list(incoming)
    total = NO_POINTS
    for week in weeks:
        total += _lineup_points(after, week) - _lineup_points(before, week)
    return total.quantize(POINT_PRECISION)


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
    of the season" -- covers the whole regular season, and a player who is back
    before week 18 locks did *not* play the last regular week for the borrower.
    So an open-ended rental returns at :data:`LAST_REGULAR_WEEK` **plus one**:
    the week after the last one it covers, which is the same arithmetic every
    bounded rental uses and the same value every bounded one is capped at.
    Week 19 is not a week anybody plays; it is how "through the end of the
    regular season" is written in the one unit this function returns.
    """
    if ask.horizon_weeks is None:
        return LAST_REGULAR_WEEK + 1
    return min(snapshot.week + ask.horizon_weeks + 1, LAST_REGULAR_WEEK + 1)


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


def _nudge(rank: int | None, weight: Decimal, *, best_first: bool) -> Decimal:
    """Turn a 1-based rank into a nudge of at most ``weight`` points.

    The place is divided by :data:`~ultimate_guillotine.advisor.scoring.LEAGUE_TEAMS`
    so the term runs from ``weight / LEAGUE_TEAMS`` at the wrong end of the
    table to ``weight`` at the right one, whatever size the league is. An
    un-normalised ``weight * place`` ran to eighteen times its own weight, and
    two such terms together spanned 3.6 points -- more than the projected
    difference between most players, so the ranking was decided by who was
    easiest to ask rather than by what the roster gained. An unranked team --
    eliminated, or below the coverage gate -- gets nothing either way rather
    than being sorted to a made-up position.
    """
    if rank is None:
        return NO_POINTS
    place = LEAGUE_TEAMS + 1 - rank if best_first else rank
    return weight * Decimal(place) / Decimal(LEAGUE_TEAMS)


def _rank_term(rank: int | None, *, neediest_first: bool) -> Decimal:
    """The need-rank nudge, worth at most :data:`NEED_RANK_WEIGHT`.

    ``neediest_first`` is which end of the list the caller wants. Selling to the
    league's neediest team is the easy sale, so a move rewards rank 1; buying
    from the team that needs the position least is the easy buy, so an acquire
    rewards the far end.
    """
    return _nudge(rank, NEED_RANK_WEIGHT, best_first=neediest_first)


def _pressure_term(rank: int | None, *, desperate_first: bool) -> Decimal:
    """The same nudge, read off the guillotine rather than off a position.

    A team about to be cut wants points this week and will pay for them, so it
    is the willing *buyer* on a move. The same team is the last one that will
    sell you a starter, so an acquire looks for the calm end of the table.
    """
    return _nudge(rank, PRESSURE_WEIGHT, best_first=desperate_first)


def _margin(
    holding: AdvisorHolding, position: str, replacement: Mapping[str, Decimal], *, known: bool
) -> Decimal | None:
    """How far the moved player projects above a free replacement, or ``None``.

    ``None`` below the coverage gate for the same reason as
    :func:`_lineup_delta`, and ``None`` when the league has no replacement level
    at the position -- an unknown margin is not a zero one.
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


def _delta_basis(
    asker_delta: Decimal | None, counterparty_delta: Decimal | None, *, known: bool
) -> DeltaBasis:
    """Say why a delta is missing, so the answer never has to guess it was zero."""
    if not known:
        return "withheld"
    if asker_delta is None or counterparty_delta is None:
        return "incomplete"
    return "lineup"


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
    #: The league's median remaining FAAB, which every default price anchors to.
    anchor: int
    weeks: tuple[int, ...]
    known: bool
    structure: Literal["permanent", "rental"]
    return_week: int | None
    return_condition: str | None

    @property
    def kinds(self) -> tuple[str, ...]:
        """The trade kinds this run's prices may be read out of.

        A rental is a loan and the league has paid loan prices for those.
        Quoting a permanent acquisition to a manager borrowing a back for three
        weeks would tell him a rental costs what keeping the player costs,
        which is the one number he did not ask for.
        """
        return ("rental",) if self.structure == "rental" else COMPARABLE_KINDS


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
        anchor=_median_budget(snapshot),
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
                candidates.extend(_acquire(run, asker, asker_team, other, team, position))
            if ask.direction != "acquire":
                candidates.extend(_move(run, asker, asker_team, other, team, position))

    candidates.sort(key=lambda candidate: candidate.sort_key)
    return _spread(candidates)[:limit]


def _spread(candidates: Sequence[Candidate]) -> list[Candidate]:
    """Keep the best :data:`MAX_PER_COUNTERPARTY` offers from any one counterparty.

    Applied to the whole sorted list rather than per position and direction,
    because that is the number a manager actually sees: an open ask crosses four
    positions and both directions, and a roster that is long everywhere would
    otherwise supply sixteen of the twelve. Taking them in sorted order means
    the ones dropped are that counterparty's *worst*, and the order of what
    survives is untouched.
    """
    kept: list[Candidate] = []
    seen: dict[int, int] = {}
    for candidate in candidates:
        taken = seen.get(candidate.counterparty_member_id, 0)
        if taken >= MAX_PER_COUNTERPARTY:
            continue
        seen[candidate.counterparty_member_id] = taken + 1
        kept.append(candidate)
    return kept


def _build(
    run: _Run,
    asker: TeamScore,
    asker_team: AdvisorTeamState,
    other: TeamScore,
    other_team: AdvisorTeamState,
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
    acquire and forgotten on a move. Each side's delta is computed against that
    side's own roster, so the two are independent numbers rather than one number
    and its negation -- see :func:`_lineup_delta`.
    """
    amount, basis, code = price
    seller, buyer = (other, asker) if to_asker else (asker, other)
    player_leg = _leg_player(holding, seller.member_label, buyer.member_label)
    faab_leg = _leg_faab(amount, buyer.member_label, seller.member_label)
    gained, given = ([holding], []) if to_asker else ([], [holding])
    asker_delta = _lineup_delta(
        _startable(asker_team), gained, given, run.weeks, known=run.known
    )
    counterparty_delta = _lineup_delta(
        _startable(other_team), given, gained, run.weeks, known=run.known
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
        asker_delta=asker_delta,
        counterparty_delta=counterparty_delta,
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
            delta_basis=_delta_basis(asker_delta, counterparty_delta, known=run.known),
        ),
    )


def _acquire(
    run: _Run,
    asker: TeamScore,
    asker_team: AdvisorTeamState,
    other: TeamScore,
    other_team: AdvisorTeamState,
    position: str,
) -> list[Candidate]:
    """The asker buys one of the counterparty's spare players and pays in FAAB.

    The fit is the asker's own need, plus how far the player is above a free
    replacement, nudged toward the counterparty least likely to say no -- the
    team that needs the position least and sits furthest from the cut line --
    and docked for what the player costs. The asker is the payer, so it is the
    asker's budget the price is clamped to.
    """
    if not _wants(asker, position, known=run.known):
        return []
    price = _price(
        run.points, position, asker_team.faab_remaining, run.anchor, kinds=run.kinds
    )
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
            run, asker, asker_team, other, other_team, position, holding,
            to_asker=True, receiver=asker, price=price, fit_base=fit_base,
        )
        for holding in other.surpluses.get(position, ())[:OFFERS_PER_COUNTERPARTY]
    ]


def _move(
    run: _Run,
    asker: TeamScore,
    asker_team: AdvisorTeamState,
    other: TeamScore,
    other_team: AdvisorTeamState,
    position: str,
) -> list[Candidate]:
    """The asker sells a spare player to a team that has a hole at that position.

    The mirror image, with both nudges reversed: the easiest sale is to the team
    with the biggest hole at the position and the least time left to fix it, and
    a bigger cheque makes the deal better rather than worse. The counterparty is
    the payer here, so the clamp is its budget -- but only the clamp: the price
    itself is the league's, so a richer counterparty cannot buy its way up the
    list with a cheque nobody asked it for.
    """
    if not _wants(other, position, known=run.known):
        return []
    price = _price(
        run.points, position, other_team.faab_remaining, run.anchor, kinds=run.kinds
    )
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
            run, asker, asker_team, other, other_team, position, holding,
            to_asker=False, receiver=other, price=price, fit_base=fit_base,
        )
        for holding in asker.surpluses.get(position, ())[:OFFERS_PER_COUNTERPARTY]
    ]
