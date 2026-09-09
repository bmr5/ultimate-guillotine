"""Deterministic name resolution and validation for extracted trades.

Sits between the model's extraction (``ExtractedTrade``, free-text names) and
persistence (``TradeProposal``, member/player ids): it maps the names people
typed to league members and Sleeper players, settles duplicate first names
using roster evidence, and validates the resulting proposal. The model is
never asked to choose between ambiguous candidates -- every disambiguation
here is deterministic.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import (
    ExtractedTrade,
    MemberRef,
    TradeAsset,
    TradeParty,
    TradeProposal,
)
from ultimate_guillotine.trades.names import normalize_name

__all__ = [
    "MemberRef",
    "RosterIndex",
    "Unresolved",
    "build_roster_index",
    "normalize_name",
    "resolve_extracted",
    "validate",
]

_DEFENSE_WORDS = {"defense", "def", "dst"}
# Generational suffixes, normalized: they are never the name anyone types.
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


class Unresolved(Exception):
    """Raised when a trade can't be resolved or validated without a human."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RosterIndex:
    """Maps a member id to the Sleeper player ids on their current roster."""

    holdings: dict[int, frozenset[str]]

    @classmethod
    def empty(cls) -> "RosterIndex":
        return cls({})

    def holds(self, member_id: int, player_id: str) -> bool:
        return player_id in self.holdings.get(member_id, frozenset())


def build_roster_index(
    client: SleeperClient, conn: psycopg.Connection, league_id: str
) -> RosterIndex:
    """Join Sleeper's roster holdings to this season's teams, by ``sleeper_roster_id``."""
    rosters = client.get_rosters(league_id)
    year = datetime.now(UTC).year
    with conn.cursor() as cur:
        cur.execute(
            """
            select t.sleeper_roster_id, t.member_id
            from public.teams t
            join public.seasons s on s.id = t.season_id
            where s.year = %s
            """,
            (year,),
        )
        roster_to_member = {row[0]: row[1] for row in cur.fetchall()}
    if not roster_to_member:
        return RosterIndex.empty()
    holdings: dict[int, frozenset[str]] = {}
    for roster in rosters:
        member_id = roster_to_member.get(roster.roster_id)
        if member_id is None:
            continue
        holdings[member_id] = frozenset(roster.players)
    return RosterIndex(holdings)


def _build_member_index(members: list[MemberRef]) -> dict[str, list[MemberRef]]:
    index: dict[str, list[MemberRef]] = {}
    for member in members:
        keys = {normalize_name(member.display_name)} | {normalize_name(a) for a in member.aliases}
        for key in keys:
            index.setdefault(key, []).append(member)
    return index


def _match_defense(norm: str, players: list[Player]) -> Player | None:
    tokens = norm.split(" ")
    if len(tokens) != 2 or tokens[1] not in _DEFENSE_WORDS:
        return None
    team_code = tokens[0].upper()
    matches = [p for p in players if p.position == "DEF" and (p.team or "").upper() == team_code]
    return matches[0] if len(matches) == 1 else None


def _last_name(norm: str) -> str | None:
    """The last name in an already-normalized name, ignoring generational suffixes.

    ``marvin harrison jr`` -> ``harrison``; a name that is nothing but suffixes
    (someone typing ``III``) has no last name and must match nobody.
    """
    tokens = [t for t in norm.split(" ") if t]
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return tokens[-1] if tokens else None


def _resolve_player(name: str, players: list[Player]) -> str:
    norm = normalize_name(name)
    exact = [p for p in players if normalize_name(p.full_name) == norm]
    if not exact:
        defense = _match_defense(norm, players)
        if defense is not None:
            exact = [defense]
    if len(exact) == 1:
        return exact[0].sleeper_player_id
    if len(exact) >= 2:
        raise Unresolved(f"Two players named {name}; which team?")

    typed_last = _last_name(norm)
    if typed_last is not None:
        last_name_matches = [
            p for p in players if _last_name(normalize_name(p.full_name)) == typed_last
        ]
        if len(last_name_matches) == 1:
            return last_name_matches[0].sleeper_player_id
        if len(last_name_matches) >= 2:
            raise Unresolved(f"Two players named {name}; which team?")

    raise Unresolved(f"I can't find a player named {name}")


def resolve_extracted(
    extracted: ExtractedTrade,
    members: list[MemberRef],
    players: list[Player],
    rosters: RosterIndex,
    season: int,
    source_guid: str,
    excerpt: str,
    prompt_version: str,
    model: str,
) -> TradeProposal:
    if extracted.kind == "unclear":
        raise Unresolved(extracted.unclear_reason or "The alert is unclear")

    member_index = _build_member_index(members)

    # Resolve every player asset first -- roster disambiguation below depends on it.
    resolved_players: dict[int, str] = {}
    for i, asset in enumerate(extracted.assets):
        # Only player assets carry a name we must resolve; a FAAB asset that
        # mentions a player in passing keeps the free text and no player id.
        if asset.kind == "player" and asset.player_name:
            resolved_players[i] = _resolve_player(asset.player_name, players)

    def sent_players(norm_name: str) -> set[str]:
        return {
            resolved_players[i]
            for i, asset in enumerate(extracted.assets)
            if asset.kind == "player"
            and asset.from_party
            and normalize_name(asset.from_party) == norm_name
            and i in resolved_players
        }

    def received_players(norm_name: str) -> set[str]:
        return {
            resolved_players[i]
            for i, asset in enumerate(extracted.assets)
            if asset.kind == "player"
            and asset.to_party
            and normalize_name(asset.to_party) == norm_name
            and i in resolved_players
        }

    member_cache: dict[str, MemberRef] = {}

    def resolve_member(name: str) -> MemberRef:
        norm = normalize_name(name)
        if norm in member_cache:
            return member_cache[norm]

        candidates = member_index.get(norm, [])
        if not candidates:
            raise Unresolved(f"I don't recognize '{name}' as a league member")
        if len(candidates) == 1:
            member_cache[norm] = candidates[0]
            return candidates[0]

        winner: MemberRef | None = None
        if len(candidates) in (2, 3):
            sent = sent_players(norm)
            received = received_players(norm)
            if sent:
                holds_all_sent = [
                    c for c in candidates if all(rosters.holds(c.member_id, p) for p in sent)
                ]
                if len(holds_all_sent) == 1:
                    winner = holds_all_sent[0]
            if winner is None and not sent and received:
                # "Holds none of what it receives" is only evidence when every
                # candidate's roster is known: a candidate missing from the index
                # holds nothing as far as we can see, which proves nothing.
                known = all(c.member_id in rosters.holdings for c in candidates)
                holds_none = [
                    c for c in candidates
                    if not any(rosters.holds(c.member_id, p) for p in received)
                ]
                if known and len(holds_none) == 1:
                    winner = holds_none[0]

        if winner is None:
            raise Unresolved(f"Two members go by '{name}'; which one?")
        member_cache[norm] = winner
        return winner

    trade_parties: list[TradeParty] = []
    seen_member_ids: set[int] = set()
    for party in extracted.parties:
        member = resolve_member(party.name)
        if member.member_id not in seen_member_ids:
            seen_member_ids.add(member.member_id)
            trade_parties.append(TradeParty(member.member_id, member.display_name))

    trade_assets: list[TradeAsset] = []
    for i, asset in enumerate(extracted.assets):
        from_id = resolve_member(asset.from_party).member_id if asset.from_party else None
        to_id = resolve_member(asset.to_party).member_id if asset.to_party else None
        trade_assets.append(
            TradeAsset(
                kind=asset.kind,
                from_member_id=from_id,
                to_member_id=to_id,
                player_id=resolved_players.get(i),
                player_name=asset.player_name,
                amount=asset.amount,
                unit=asset.unit,
                description=asset.description,
            )
        )

    return TradeProposal(
        season=season,
        effective_week=extracted.effective_week,
        kind=extracted.kind,
        parties=trade_parties,
        assets=trade_assets,
        rental_return_condition=extracted.rental_return_condition,
        special_terms=extracted.special_terms,
        referenced_trade_code=extracted.referenced_trade_code,
        source_message_guid=source_guid,
        evidence_excerpt=excerpt,
        prompt_version=prompt_version,
        model=model,
    )


def validate(proposal: TradeProposal) -> None:
    if len(proposal.parties) < 2:
        raise Unresolved("A trade needs at least two parties")
    if not proposal.assets:
        raise Unresolved("A trade needs at least one asset")
    for asset in proposal.assets:
        if asset.amount is not None and asset.unit is None:
            raise Unresolved("An amount needs a unit")
    if proposal.kind == "rental" and not proposal.rental_return_condition:
        raise Unresolved("A rental needs a return condition")
