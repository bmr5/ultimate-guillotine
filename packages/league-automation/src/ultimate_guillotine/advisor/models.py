"""The strict schema the one model call must answer in.

Every bound here is also re-checked deterministically in ``verify.py``: the
schema stops a malformed answer, and the verifier stops a well-formed answer
that made something up. Neither is enough on its own.

``candidate_index`` is what ties the two together. The model is handed a
numbered list of candidates and may only rank them, so every proposal has to say
which number it is talking about; the verifier looks that number up and compares
the legs, the counterparty and the price it was given against the candidate that
was really generated. An index nobody handed out -- or legs that do not match
the candidate the index names -- is a fabrication, and it is rejected there.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The most proposals one answer may carry, and so the worst rank there is.
#: Bounding ``rank`` at the same number the list is bounded at means a fourth
#: place cannot be written down even in principle.
MAX_PROPOSALS = 3

AdviceStatus = Literal["ok", "no_good_trades", "insufficient_data"]
Structure = Literal["permanent", "rental", "multi_team"]
LegKind = Literal["player", "faab"]


class OfferLeg(BaseModel):
    """One thing moving one way, copied from the candidate rather than composed.

    ``player_id`` is carried so the verifier can match on the id instead of on a
    name a model might respell. FAAB legs carry ``amount`` and no player; player
    legs carry the player and no amount. Nothing else is a leg: there is no kind
    for cash, for dues credit, or for a draft pick, so the schema cannot express
    a currency the league does not trade.

    Those two shapes are enforced rather than described. A player leg with an
    ``amount`` is a player being sold for a number nobody quoted, and a FAAB leg
    with a player name attached is a second player smuggled into a leg the
    verifier would price as money -- so both are rejected here, before anything
    downstream has to decide which half of the leg to believe.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: LegKind
    player_id: str | None = None
    player_name: str | None = None
    #: Whole FAAB dollars. There is no such thing as a zero-dollar leg -- that is
    #: a leg that should not have been written -- so the floor is one.
    amount: int | None = Field(default=None, ge=1)
    from_member: str
    to_member: str

    @model_validator(mode="after")
    def validate_leg_shape(self) -> "OfferLeg":
        if self.kind == "player":
            if not self.player_id or not self.player_name:
                raise ValueError("a player leg must carry the player's id and name")
            if self.amount is not None:
                raise ValueError("a player leg carries no amount")
            return self
        if self.amount is None:
            raise ValueError("a faab leg must carry an amount")
        if self.player_id is not None or self.player_name is not None:
            raise ValueError("a faab leg names no player")
        return self


class AdvisedTrade(BaseModel):
    """One ranked proposal: which candidate, in what order, and why.

    The prose is bounded because it is going into a group chat, and because a
    long enough leash is where a model starts explaining figures it was never
    given. ``reasoning`` gets two sentences and ``risk`` gets one line.

    A ``rental`` must say when the player comes home. The candidate that was
    handed over already carries the sentence, so a rental with no
    ``return_condition`` is not an incomplete answer to copy from -- it is an
    answer that dropped the one term that makes a rental a rental, and it is
    rejected here rather than rendered into a chat as a permanent trade.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The 1-based number of the candidate this ranks, as the facts block
    #: labelled it. Opaque to the model: it means nothing but "this one".
    candidate_index: int = Field(ge=1)
    rank: int = Field(ge=1, le=MAX_PROPOSALS)
    counterparties: list[str] = Field(min_length=1, max_length=2)
    asker_receives: list[OfferLeg] = []
    asker_sends: list[OfferLeg] = []
    structure: Structure
    return_condition: str | None = None
    reasoning: str = Field(max_length=240)
    risk: str = Field(max_length=140)
    comparable_trade_code: str | None = None

    @model_validator(mode="after")
    def validate_rental_returns(self) -> "AdvisedTrade":
        if self.structure == "rental" and not self.return_condition:
            raise ValueError("a rental must carry the candidate's return condition")
        return self


class TradeAdviceResponse(BaseModel):
    """The whole answer. At most three proposals, and honest emptiness allowed.

    ``no_good_trades`` and ``insufficient_data`` are first-class answers, not
    failures: the schema does not require a proposal, so the model never has to
    invent one to satisfy it.

    The ranks are checked as a set, not one at a time. Two proposals both ranked
    1, or a 1 and a 3 with nothing between them, is an ordering the renderer
    would have to guess at -- so a response's ranks must be exactly ``1..n`` for
    the ``n`` proposals it carries, once each.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AdviceStatus
    headline: str = Field(max_length=120)
    proposals: list[AdvisedTrade] = Field(default=[], max_length=MAX_PROPOSALS)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_ranks_are_a_full_order(self) -> "TradeAdviceResponse":
        ranks = sorted(proposal.rank for proposal in self.proposals)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("proposals must be ranked 1, 2, 3 with no gaps and no repeats")
        return self
