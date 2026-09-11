"""The words on the video.

Two layers, both copied from the reference TikTok: a caption in the middle of
the footage ("pov: …", sentence case) and an ESPN-style lower third that
carries the actual trade -- a red tag, an upper-case headline, a subline that
says what each side gets in the chat's own wording. A third layer is never
drawn: the trade fact by fact, for whoever writes the on-air read.
"""

from dataclasses import dataclass

from ultimate_guillotine.trades.format import Labels, asset_words, party_labels, party_receives
from ultimate_guillotine.trades.models import TradeProposal

LEAGUE = "the Sovereign Guillotine League"

#: What a member is called on air when it is not their nickname, by Sleeper
#: display name. Ben (2026-09-10): "instead of calling me Ben R please call me
#: Commish in all videos or just Ben". The chat and the board keep the nickname.
ON_AIR_NAMES = {"benray887": "the Commish"}


@dataclass(frozen=True)
class TradeCopy:
    caption: str
    headline: str
    subline: str
    tag: str = "BREAKING NEWS"
    #: The small line at the foot of the bar, where ESPN puts its own strap.
    footer: str = "THE SOVEREIGN GUILLOTINE LEAGUE · TRADE REGISTRAR"
    #: The trade fact by fact, for the writer of the read: the announcement as
    #: it was posted, then who gives what to whom. The lower third compresses,
    #: and a read written from it alone once put the wrong man in the gulag.
    facts: tuple[str, ...] = ()


def on_air_labels(members) -> Labels:
    """``party_labels`` with the on-air names on top."""
    labels = party_labels(members)
    for member in members:
        for name in (
            getattr(member, "sleeper_display_name", None),
            getattr(member, "display_name", None),
        ):
            if name in ON_AIR_NAMES:
                labels[member.member_id] = ON_AIR_NAMES[name]
                break
    return labels


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


def _capitalized(text: str) -> str:
    return text[:1].upper() + text[1:]


def _obligations(proposal: TradeProposal) -> list[str]:
    """An ``other`` asset in the announcer's own words, when there is one.

    ``go to gulag for Ben`` is what the model wrote down, so ``Ben R gets go to
    gulag for Ben`` is what the bar used to say. The special terms carry the
    sentence the announcer wrote; the bar shows that instead.
    """
    if not any(asset.kind == "other" for asset in proposal.assets):
        return []
    return [term.strip().rstrip(".") for term in proposal.special_terms if term.strip()]


def subline(proposal: TradeProposal, labels: Labels) -> str:
    obligations = _obligations(proposal)
    shown = proposal
    if obligations:
        shown = proposal.model_copy(
            update={"assets": [asset for asset in proposal.assets if asset.kind != "other"]}
        )
    parts = []
    for party in proposal.parties:
        got = party_receives(shown, party.member_id)
        if got == "nothing" and obligations:
            continue
        parts.append(f"{labels.get(party.member_id, party.display_name)} gets {got}")
    parts.extend(obligations)
    if proposal.effective_week is not None:
        parts.append(f"Week {proposal.effective_week}")
    return " · ".join(_capitalized(part) for part in parts)


def facts(proposal: TradeProposal, labels: Labels) -> tuple[str, ...]:
    """The trade fact by fact, in sentences the writer can trust.

    The announcement comes first and verbatim: when the model's breakdown and
    the announcer's sentence disagree, the sentence is what happened.
    """
    lines = [f"Announced in the league chat as: {' '.join(proposal.evidence_excerpt.split())}"]
    for asset in proposal.assets:
        words = asset_words(asset)
        if words is None:
            continue
        giver = _name_of(proposal, labels, asset.from_member_id) or "someone"
        taker = _name_of(proposal, labels, asset.to_member_id) or "someone"
        if asset.kind == "other":
            lines.append(f"{giver} owes {taker}: {words} (an obligation, not a player or money)")
        else:
            lines.append(f"{giver} gives {taker}: {words}")
    for term in proposal.special_terms:
        lines.append(f"Special term, in the announcer's words: {term}")
    if proposal.rental_return_condition:
        lines.append(f"Rental, returned: {proposal.rental_return_condition}")
    if proposal.effective_week is not None:
        lines.append(f"Effective week {proposal.effective_week}")
    return tuple(lines)


def trade_copy(
    proposal: TradeProposal, labels: Labels | None = None, caption: str | None = None
) -> TradeCopy:
    labels = labels or {}
    return TradeCopy(
        caption=caption or default_caption(_names(proposal, labels)),
        headline=headline(proposal, labels),
        subline=subline(proposal, labels),
        facts=facts(proposal, labels),
    )
