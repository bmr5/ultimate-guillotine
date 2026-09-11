"""The one shape the agent's final turn takes: ``LeagueAnswer``.

The chat text is what the league sees; the report is what the artifact is
made of; the facts are what the verifier checks. A leg has four kinds and no
fifth -- there is no way to write down cash, Venmo or dues credit -- and a
``term`` leg is free text on purpose, because the rulebook invites options,
insurance and holds that no fixed schema could enumerate. Facts are what get
checked; terms are what get read.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ultimate_guillotine.ai.structured import parse_model_text

#: Plain text for a phone. Long enough for a headline and three option lines.
CHAT_TEXT_LIMIT = 1200
#: The report body before the template wraps it; the rendered cap is checked later.
REPORT_BODY_LIMIT = 200_000

AnswerKind = Literal["answer", "clarification", "refusal"]
LegKind = Literal["player", "faab", "draft_dollars", "term"]
FaabClaim = Literal["balance", "offer"]


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    url: str = Field(max_length=500)
    claim: str = Field(max_length=200)


class Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str = Field(min_length=1, max_length=120)
    #: The member's question as the agent restates it -- what the page shows.
    question: str = Field(default="", max_length=300)
    html_body: str = Field(min_length=1, max_length=REPORT_BODY_LIMIT)
    sources: list[Source] = []


class ProposalLeg(BaseModel):
    """One thing moving one way: a player, whole FAAB dollars, draft dollars, or a term."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: LegKind
    player_id: str | None = None
    player_name: str | None = None
    amount: int | None = Field(default=None, ge=1)
    text: str | None = Field(default=None, max_length=240)
    from_member: str = Field(max_length=80)
    to_member: str = Field(max_length=80)

    @model_validator(mode="after")
    def validate_shape(self) -> "ProposalLeg":
        if self.kind == "player" and not (self.player_id or self.player_name):
            raise ValueError("a player leg names a player")
        if self.kind in ("faab", "draft_dollars") and self.amount is None:
            raise ValueError("a money leg carries an amount")
        if self.kind == "term" and not self.text:
            raise ValueError("a term leg says what the term is")
        return self


class Proposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    title: str = Field(max_length=120)
    counterparties: list[str] = Field(min_length=1, max_length=3)
    legs: list[ProposalLeg] = Field(min_length=1)


class PlayerFact(BaseModel):
    """Where the answer says a player is: a member's label, or ``free agent``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    player_id: str | None = None
    name: str = Field(max_length=80)
    holder: str = Field(max_length=80)


class FaabFact(BaseModel):
    """A FAAB number the answer states: somebody's balance, or an amount offered."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    member: str = Field(max_length=80)
    amount: int = Field(ge=0)
    claim: FaabClaim = "balance"


class Facts(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    players: list[PlayerFact] = []
    faab: list[FaabFact] = []
    proposals: list[Proposal] = []


class LeagueAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: AnswerKind
    chat_text: str = Field(min_length=1, max_length=CHAT_TEXT_LIMIT)
    report: Report | None = None
    facts: Facts = Facts()
    source_line: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def validate_report_only_on_answers(self) -> "LeagueAnswer":
        if self.kind != "answer" and self.report is not None:
            raise ValueError("only an answer carries a report")
        return self


FREE_AGENT = "free agent"


def extract_answer(text: str) -> LeagueAnswer:
    """The ``LeagueAnswer`` in the agent's final turn, or ``AIInvalidOutput``.

    ``parse_model_text`` does the tolerating -- a fence and a sentence either
    side of the object are normal -- and raises ``AIInvalidOutput`` for anything
    that is not this contract. Nothing here catches that: a final turn the
    schema rejects is not an answer, and there is no salvaging one.
    """
    return parse_model_text(text, LeagueAnswer)
