import hashlib
import json

from ultimate_guillotine.trades.models import TradeAsset, TradeProposal


def message_fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()


def _canonical_asset(asset: TradeAsset) -> list:
    return [
        asset.kind, asset.from_member_id, asset.to_member_id, asset.player_id,
        (asset.player_name or "").lower(), asset.amount, asset.unit,
        " ".join((asset.description or "").split()).lower(),
    ]


def trade_fingerprint(proposal: TradeProposal) -> str:
    canonical = {
        "season": proposal.season,
        "week": proposal.effective_week,
        "kind": proposal.kind,
        "parties": sorted(p.member_id for p in proposal.parties),
        "assets": sorted(
            (_canonical_asset(a) for a in proposal.assets),
            key=lambda c: json.dumps(c, default=str),
        ),
        "return": " ".join((proposal.rental_return_condition or "").split()).lower(),
        "special": sorted(" ".join(t.split()).lower() for t in proposal.special_terms),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()


def trade_context_key(proposal: TradeProposal) -> str:
    """The key an amended announcement is matched against its original by.

    Season, parties and players: an amount that changed between two postings of
    the same deal must not change the key, or the correction would land as a
    second trade rather than a revision.

    A proposal with no player asset at all -- a payment, a FAAB-only deal -- has
    nothing left to tell two deals apart, and season plus parties would make
    every later payment between the same pair a revision of the first. Those
    keys carry the semantic fingerprint instead, so they only ever match an
    identical proposal (which the fingerprint already catches as a duplicate).
    """
    players = sorted(
        a.player_id or (a.player_name or "").lower()
        for a in proposal.assets
        if a.kind == "player"
    )
    parties = ",".join(str(p) for p in sorted(p.member_id for p in proposal.parties))
    if not players:
        return f"{proposal.season}:{parties}:nfp:{trade_fingerprint(proposal)}"
    return f"{proposal.season}:{parties}:{','.join(players)}"
