from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

TradeKind = Literal["permanent", "rental", "payment", "rescission", "unclear", "not_a_trade"]
AssetKind = Literal["player", "faab", "draft_dollars", "usd", "protection", "other"]
AssetUnit = Literal["faab", "draft_dollars", "usd"]


class ExtractedParty(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str


class ExtractedAsset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: AssetKind
    from_party: str | None = None
    to_party: str | None = None
    player_name: str | None = None
    amount: int | None = None
    unit: AssetUnit | None = None
    description: str | None = None


class ExtractedTrade(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: TradeKind
    parties: list[ExtractedParty] = []
    assets: list[ExtractedAsset] = []
    effective_week: int | None = None
    rental_return_condition: str | None = None
    special_terms: list[str] = []
    referenced_trade_code: str | None = None
    unclear_reason: str | None = None


@dataclass(frozen=True)
class MemberRef:
    """A league member and the names resolution may match them by.

    Lives here rather than in ``trades.resolve`` so ``data.repositories`` can
    return one without importing the Sleeper HTTP client.

    ``nickname`` carries the value of ``public.members.nickname``: the member's
    first alias, and the one alias the league publishes. The board and the
    Concierge render it as the owner's label, so it is public by design; every
    other alias stays in ``private.member_aliases``. It defaults to ``None`` for
    a member with no aliases, and trade resolution matches on ``aliases``, never
    on this.
    """

    member_id: int
    display_name: str
    aliases: tuple[str, ...]
    nickname: str | None = None


@dataclass(frozen=True)
class TradeParty:
    member_id: int
    display_name: str


@dataclass(frozen=True)
class TradeAsset:
    kind: str
    from_member_id: int | None
    to_member_id: int | None
    player_id: str | None
    player_name: str | None
    amount: int | None
    unit: str | None
    description: str | None


class TradeProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    season: int
    effective_week: int | None = None
    kind: TradeKind
    parties: list[TradeParty] = []
    assets: list[TradeAsset] = []
    rental_return_condition: str | None = None
    special_terms: list[str] = []
    referenced_trade_code: str | None = None
    source_message_guid: str
    evidence_excerpt: str
    prompt_version: str
    model: str
