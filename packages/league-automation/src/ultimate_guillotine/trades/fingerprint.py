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
        "assets": sorted(_canonical_asset(a) for a in proposal.assets),
        "return": " ".join((proposal.rental_return_condition or "").split()).lower(),
        "special": sorted(" ".join(t.split()).lower() for t in proposal.special_terms),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()


def trade_context_key(proposal: TradeProposal) -> str:
    players = sorted(
        a.player_id or (a.player_name or "").lower()
        for a in proposal.assets
        if a.kind == "player"
    )
    parties = sorted(p.member_id for p in proposal.parties)
    return f"{proposal.season}:{','.join(map(str, parties))}:{','.join(players)}"
