"""Chat text for logged trades, revisions, rescissions and clarifications.

The registrar posts these into the league chat through the delivery service,
which appends its own signature -- nothing here ever does.
"""

from typing import Any

from ultimate_guillotine.trades.models import TradeProposal

__all__ = [
    "format_clarification",
    "format_confirmation",
    "format_rescinded",
    "format_updated",
]

# Asset kinds that carry a number rather than a name or a description. They
# double as the unit when an asset leaves ``unit`` unset.
_AMOUNT_KINDS = ("faab", "usd", "draft_dollars")
_UNIT_LABELS = {"faab": "FAAB", "draft_dollars": "draft dollars"}


def _format_amount(kind: str, amount: object, unit: str | None) -> str:
    unit = unit or (kind if kind in _AMOUNT_KINDS else None)
    if unit == "usd":
        return f"${amount}"
    label = _UNIT_LABELS.get(unit or "")
    return f"{amount} {label}" if label else f"{amount}"


def _receives(proposal: TradeProposal, member_id: int) -> str:
    """What one party gets: players, then amounts, then other terms."""
    players: list[str] = []
    amounts: list[str] = []
    others: list[str] = []
    for asset in proposal.assets:
        if asset.to_member_id != member_id:
            continue
        if asset.kind == "player":
            name = asset.player_name or asset.player_id
            if name:
                players.append(name)
        elif asset.amount is not None:
            amounts.append(_format_amount(asset.kind, asset.amount, asset.unit))
        elif asset.kind not in _AMOUNT_KINDS:
            others.append(asset.description or asset.kind)
    parts = players + amounts + others
    return " + ".join(parts) if parts else "nothing"


def _kind_label(proposal: TradeProposal) -> str:
    if proposal.kind == "rental" and proposal.rental_return_condition:
        return f"Rental ({proposal.rental_return_condition})"
    return proposal.kind.capitalize()


def _body(proposal: TradeProposal) -> list[str]:
    lines = [
        f"{party.display_name} receives: {_receives(proposal, party.member_id)}"
        for party in proposal.parties
    ]
    week = "?" if proposal.effective_week is None else proposal.effective_week
    lines.append(f"Week {week} · {_kind_label(proposal)}")
    if proposal.special_terms:
        lines.append("Terms: " + "; ".join(proposal.special_terms))
    return lines


def _current_amounts(proposal: TradeProposal) -> list[str]:
    return [
        _format_amount(asset.kind, asset.amount, asset.unit)
        for asset in proposal.assets
        if asset.amount is not None
    ]


def _previous_amounts(previous_terms: dict[str, Any]) -> list[str]:
    assets = previous_terms.get("assets") or []
    return [
        _format_amount(asset.get("kind", ""), asset.get("amount"), asset.get("unit"))
        for asset in assets
        if asset.get("amount") is not None
    ]


def format_confirmation(code: str, proposal: TradeProposal) -> str:
    """The message posted when a trade is logged for the first time."""
    return "\n".join([f"🚨 Trade {code} logged", *_body(proposal)])


def format_updated(code: str, proposal: TradeProposal, previous_terms: dict[str, Any]) -> str:
    """The message posted when a logged trade is revised.

    ``previous_terms`` is the prior revision's ``TradeProposal.model_dump()``.
    When its amounts differ from the new ones, a ``Was:`` line spells the old
    ones out so the chat can see exactly what moved.
    """
    lines = [f"🚨 Trade {code} updated", *_body(proposal)]
    previous = _previous_amounts(previous_terms)
    if sorted(previous) != sorted(_current_amounts(proposal)):
        lines.append("Was: " + (", ".join(previous) if previous else "nothing"))
    return "\n".join(lines)


def format_rescinded(code: str) -> str:
    return f"🚨 Trade {code} rescinded"


def format_clarification(reason: str) -> str:
    return f"🚨 Trade not logged yet: {reason} Reply with a corrected 🚨 alert."
