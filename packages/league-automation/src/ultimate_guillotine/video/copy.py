"""The words on the video.

Two layers, both copied from the reference TikTok: a caption in the middle of
the footage ("pov: …", sentence case) and an ESPN-style lower third that
carries the actual trade -- a red tag, an upper-case headline, a subline that
says what each side gets in the chat's own wording.
"""

from dataclasses import dataclass

from ultimate_guillotine.trades.format import Labels, party_receives
from ultimate_guillotine.trades.models import TradeProposal

LEAGUE = "the Sovereign Guillotine League"


@dataclass(frozen=True)
class TradeCopy:
    caption: str
    headline: str
    subline: str
    tag: str = "BREAKING NEWS"


def default_caption(names: list[str]) -> str:
    if len(names) >= 2:
        return (
            f"pov: the league chat when {names[0]} and {names[1]} "
            "pull off a trade nobody saw coming"
        )
    if names:
        return f"pov: the league chat when {names[0]} pulls off a trade nobody saw coming"
    return "pov: the league chat when a trade nobody saw coming goes through"


def _names(proposal: TradeProposal, labels: Labels) -> list[str]:
    return [labels.get(party.member_id, party.display_name) for party in proposal.parties]


def _name_of(proposal: TradeProposal, labels: Labels, member_id: int | None) -> str | None:
    for party in proposal.parties:
        if party.member_id == member_id:
            return labels.get(party.member_id, party.display_name)
    return None


def headline(proposal: TradeProposal, labels: Labels) -> str:
    """``SOURCES: PLAYER TRADED TO OWNER`` when a named player moves; otherwise
    the two parties, the way ESPN would put a deal with no marquee name."""
    player = next((a for a in proposal.assets if a.kind == "player" and a.player_name), None)
    if player is not None:
        receiver = _name_of(proposal, labels, player.to_member_id)
        if receiver:
            return f"SOURCES: {player.player_name} TRADED TO {receiver}".upper()
        return f"SOURCES: {player.player_name} ON THE MOVE".upper()
    names = _names(proposal, labels)
    if len(names) >= 2:
        return f"SOURCES: {names[0]} AND {names[1]} AGREE TO A TRADE".upper()
    return f"SOURCES: TRADE AGREED IN {LEAGUE}".upper()


def subline(proposal: TradeProposal, labels: Labels) -> str:
    parts = [
        f"{labels.get(party.member_id, party.display_name)} gets "
        f"{party_receives(proposal, party.member_id)}"
        for party in proposal.parties
    ]
    if proposal.effective_week is not None:
        parts.append(f"Week {proposal.effective_week}")
    return " · ".join(parts)


def trade_copy(
    proposal: TradeProposal, labels: Labels | None = None, caption: str | None = None
) -> TradeCopy:
    labels = labels or {}
    return TradeCopy(
        caption=caption or default_caption(_names(proposal, labels)),
        headline=headline(proposal, labels),
        subline=subline(proposal, labels),
    )
