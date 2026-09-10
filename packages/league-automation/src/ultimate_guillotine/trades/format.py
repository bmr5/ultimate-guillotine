"""Chat text for logged trades, revisions, rescissions and clarifications.

The registrar posts these into the league chat through the delivery service,
which appends its own signature -- nothing here ever does.
"""

from typing import Any

from ultimate_guillotine.trades.models import TradeAsset, TradeProposal

__all__ = [
    "format_clarification",
    "format_confirmation",
    "format_rescinded",
    "format_terms",
    "format_updated",
    "party_labels",
]

# A member id -> the label the board shows for that owner (nickname, else the
# Sleeper display name); anything missing falls back to the proposal's own
# ``display_name``, the bare Sleeper username.
Labels = dict[int, str]

# Asset kinds that carry a number rather than a name or a description. They
# double as the unit when an asset leaves ``unit`` unset.
_AMOUNT_KINDS = ("faab", "usd", "draft_dollars")
_UNIT_LABELS = {"faab": "FAAB", "draft_dollars": "draft dollars"}


def _format_amount(kind: str, amount: int | None, unit: str | None) -> str:
    """``450 FAAB``, ``$25``, ``-$25``, ``30 draft dollars``."""
    unit = unit or (kind if kind in _AMOUNT_KINDS else None)
    if unit == "usd":
        sign, magnitude = ("-", -amount) if amount is not None and amount < 0 else ("", amount)
        return f"{sign}${magnitude}"
    label = _UNIT_LABELS.get(unit or "")
    return f"{amount} {label}" if label else f"{amount}"


def _asset_part(asset: TradeAsset) -> str | None:
    """One asset as chat text, or ``None`` when it has nothing to say.

    The kind decides the shape: a player is a name, a numeric kind is an
    amount, and everything else (``protection``, ``other``) is its description
    even when it also carries a number -- a bare ``1`` would read as nonsense.
    """
    if asset.kind == "player":
        return asset.player_name or asset.player_id or "a player"
    if asset.kind in _AMOUNT_KINDS:
        if asset.amount is None:
            return None
        return _format_amount(asset.kind, asset.amount, asset.unit)
    return asset.description or asset.kind


def _receives(proposal: TradeProposal, member_id: int) -> str:
    """What one party gets: players, then amounts, then other terms."""
    players: list[str] = []
    amounts: list[str] = []
    others: list[str] = []
    for asset in proposal.assets:
        if asset.to_member_id != member_id:
            continue
        part = _asset_part(asset)
        if part is None:
            continue
        if asset.kind == "player":
            players.append(part)
        elif asset.kind in _AMOUNT_KINDS:
            amounts.append(part)
        else:
            others.append(part)
    parts = players + amounts + others
    return " + ".join(parts) if parts else "nothing"


def _unassigned(proposal: TradeProposal) -> list[str]:
    """Assets no listed party receives, in proposal order.

    A missing or unrecognised ``to_member_id`` would otherwise drop the asset
    out of the message entirely; the chat sees it under ``Also:`` instead.
    """
    recipients = {party.member_id for party in proposal.parties}
    parts: list[str] = []
    for asset in proposal.assets:
        if asset.to_member_id in recipients:
            continue
        part = _asset_part(asset)
        if part is not None:
            parts.append(part)
    return parts


def _kind_label(proposal: TradeProposal) -> str:
    if proposal.kind == "rental" and proposal.rental_return_condition:
        return f"Rental ({proposal.rental_return_condition})"
    return proposal.kind.capitalize()


def _body(proposal: TradeProposal) -> list[str]:
    lines = [
        f"{party.display_name} receives: {_receives(proposal, party.member_id)}"
        for party in proposal.parties
    ]
    unassigned = _unassigned(proposal)
    if unassigned:
        lines.append("Also: " + " + ".join(unassigned))
    week = "?" if proposal.effective_week is None else proposal.effective_week
    lines.append(f"Week {week} · {_kind_label(proposal)}")
    if proposal.special_terms:
        lines.append("Terms: " + "; ".join(proposal.special_terms))
    return lines


def _current_amounts(proposal: TradeProposal) -> list[str]:
    """Every amount the chat can see, in the same shape `Was:` prints them.

    Only the numeric kinds count: `_asset_part` prints a `protection` or `other`
    asset as its description, so a stray number on one of those never appears in
    the message and must not make the two revisions look different.
    """
    return [
        _format_amount(asset.kind, asset.amount, asset.unit)
        for asset in proposal.assets
        if asset.amount is not None and asset.kind in _AMOUNT_KINDS
    ]


def _previous_amounts(previous_terms: dict[str, Any]) -> list[str]:
    assets = previous_terms.get("assets") or []
    return [
        _format_amount(asset.get("kind", ""), asset.get("amount"), asset.get("unit"))
        for asset in assets
        if asset.get("amount") is not None and asset.get("kind") in _AMOUNT_KINDS
    ]


def party_labels(members) -> Labels:
    """The owner label per member id, the way the board renders it.

    ``members`` are ``MemberRef``s: nickname first, then the Sleeper display
    name. A member with neither is left out, so the proposal's own
    ``display_name`` is what the chat sees for them.
    """
    labels: Labels = {}
    for member in members:
        label = getattr(member, "nickname", None) or getattr(member, "sleeper_display_name", None)
        if label:
            labels[member.member_id] = label
    return labels


def _parties_line(proposal: TradeProposal, labels: Labels | None) -> str:
    labels = labels or {}
    return " ↔ ".join(labels.get(p.member_id, p.display_name) for p in proposal.parties)


def format_confirmation(code: str, proposal: TradeProposal, labels: Labels | None = None) -> str:
    """The one line posted when a trade is logged.

    Ben (2026-09-10): "I'd like the bot only to respond with confirmation that
    the trade has been logged, nothing else." The terms are stored in full and
    read back by ``format_terms`` for the operator, never by the chat.
    """
    return f"🚨 Trade {code} logged · {_parties_line(proposal, labels)}"


def format_updated(
    code: str,
    proposal: TradeProposal,
    previous_terms: dict[str, Any],
    labels: Labels | None = None,
) -> str:
    """The one line posted when a logged trade is revised.

    ``previous_terms`` is kept in the signature for the registrar's call and
    for ``format_terms``; the chat no longer sees a ``Was:`` line.
    """
    del previous_terms
    return f"🚨 Trade {code} updated · {_parties_line(proposal, labels)}"


def format_terms(proposal: TradeProposal, previous_terms: dict[str, Any] | None = None) -> str:
    """The full terms, for the operator (``ug trades show``), never for the chat.

    ``previous_terms`` is the prior revision's ``TradeProposal.model_dump()``;
    when its amounts differ from the new ones a ``Was:`` line spells the old
    ones out.
    """
    lines = list(_body(proposal))
    if previous_terms is not None:
        previous = _previous_amounts(previous_terms)
        if sorted(previous) != sorted(_current_amounts(proposal)):
            lines.append("Was: " + (", ".join(previous) if previous else "nothing"))
    return "\n".join(lines)


def format_rescinded(code: str) -> str:
    return f"🚨 Trade {code} rescinded"


def format_clarification(reason: str) -> str:
    return f"🚨 Trade not logged yet: {reason} Reply with a corrected 🚨 alert."
