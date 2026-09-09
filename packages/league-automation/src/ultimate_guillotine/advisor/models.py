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

from pydantic import BaseModel, ConfigDict, Field

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
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: LegKind
    player_id: str | None = None
    player_name: str | None = None
    amount: int | None = None
    from_member: str
    to_member: str


class AdvisedTrade(BaseModel):
    """One ranked proposal: which candidate, in what order, and why.

    The prose is bounded because it is going into a group chat, and because a
    long enough leash is where a model starts explaining figures it was never
    given. ``reasoning`` gets two sentences and ``risk`` gets one line.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The 1-based number of the candidate this ranks, as the facts block
    #: labelled it. Opaque to the model: it means nothing but "this one".
    candidate_index: int = Field(ge=1)
    rank: int = Field(ge=1)
    counterparties: list[str] = Field(min_length=1, max_length=2)
    asker_receives: list[OfferLeg] = []
    asker_sends: list[OfferLeg] = []
    structure: Structure
    return_condition: str | None = None
    reasoning: str = Field(max_length=240)
    risk: str = Field(max_length=140)
    comparable_trade_code: str | None = None


class TradeAdviceResponse(BaseModel):
    """The whole answer. At most three proposals, and honest emptiness allowed.

    ``no_good_trades`` and ``insufficient_data`` are first-class answers, not
    failures: the schema does not require a proposal, so the model never has to
    invent one to satisfy it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AdviceStatus
    headline: str = Field(max_length=120)
    proposals: list[AdvisedTrade] = Field(default=[], max_length=3)
    note: str | None = Field(default=None, max_length=200)
