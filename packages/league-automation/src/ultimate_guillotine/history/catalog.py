"""Read the analyst's trade classification into rows fit for a public table.

The file is private and stays private. Fields are copied through an allowlist rather
than by deleting `notes` and `source_texts` from a copy, so a field the analyst adds
next month is dropped by default instead of published by default -- which is the
difference between a privacy rule and a privacy habit.

The file's own shape is not the table's. A record keeps its assets as parallel lists
(`players`, `positions`, `faab`, `return_conditions`) and its date as one field holding
both a week and a calendar date; the table keeps assets as closed kind-objects and the
date as two columns. This module is that translation, and every step of it is lossy on
purpose: a player name that matches no active player keeps the name and loses the id, a
party nobody answers to becomes a count, and a return condition the league did not say
in one of a handful of standard ways is dropped entirely. Those free-text conditions are
most of the file -- they are sentences out of the group chat, naming who owes whom what,
and they are exactly what a public page must never carry.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from ultimate_guillotine.history.models import CatalogRow
from ultimate_guillotine.sleeper.players import SKILL_POSITIONS, Player
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name

# The catalog matches player names exactly the way the registrar does -- including its
# defense and bare-surname rules -- so it calls the registrar's matcher rather than
# growing a second one that drifts from it.
from ultimate_guillotine.trades.resolve import Unresolved, _resolve_player

#: The only keys read from a classification record. `notes` and `source_texts` are absent
#: on purpose and adding either is a privacy regression, not a feature. `source` is absent
#: too: it says which private artefact the analyst read, which is nobody's business but his.
CATALOG_FIELDS = (
    "id", "season", "week_or_date", "type", "structure", "parties", "assets",
    "faab_total", "confidence",
)

#: A return condition is a label from this closed set, never prose. The database's
#: `trade_catalog_assets_ok` holds the same five values.
CONDITION_LABELS = frozenset({"rental", "return_after_week", "conditional", "keeper", "two_way"})

CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})

#: The whole vocabulary of return conditions the catalog will publish. The analyst writes
#: them as free text, so this maps the handful of standard phrasings the league actually
#: uses onto labels and drops everything else -- and "drops" is the right default, because
#: the long tail is sentences naming members, players and dollar figures. Only generic
#: phrasings appear here: a phrase that names a person is not a term of art, it is gossip.
#: Negations ("no gulag protections") are absent deliberately. They record the *absence*
#: of a clause, and publishing them as `conditional` would invert what they said.
_PHRASES_BY_LABEL: dict[str, tuple[str, ...]] = {
    "rental": (
        "rental", "hold", "this week", "1 week", "one week", "1 week hold", "one week hold",
        "bye week hold", "1 week rental", "one week rental", "1-week rental", "1 week rentals",
        "hold / 1 week rental",
    ),
    "two_way": (
        "swap", "1 week swap", "one week swap", "1 week both ways", "1 week rental swap",
        "one week swap, players swapped back next week",
    ),
    "conditional": (
        "gulag protections", "gulag protected", "with protections", "standard protections",
        "gulag protections both ways",
    ),
    "keeper": ("all permanent", "permanent deal", "hold becomes permanent"),
    "return_after_week": (
        "players returned", "players returned on survival", "players returned per the rental deal",
        "players swapped back next week",
    ),
}

#: The same table, keyed by the normalized phrase the lookup actually sees.
CONDITION_PHRASES: dict[str, str] = {
    normalize_name(phrase): label
    for label, phrases in _PHRASES_BY_LABEL.items()
    for phrase in phrases
}

#: The validators cap a published string at 120 characters. A player name is far shorter
#: than that, so anything longer is not a name -- it is prose, and it is dropped whole
#: rather than truncated, because half a sentence is still a sentence.
MAX_NAME_LENGTH = 120

#: Sentinel for a label two different members answer to. Kept in the index so an ambiguous
#: token is recognised as ambiguous rather than simply missing.
AMBIGUOUS = None


@dataclass(frozen=True)
class CatalogReading:
    """One classification record, read down to what a public row may carry.

    The dropped conditions ride alongside the row rather than in it: they are a fact
    about this run of the loader, not about the trade, and the table has no column for
    a thing that was refused.
    """

    row: CatalogRow
    unmapped_conditions: int


class PlayerIndex:
    """Sleeper ids for the player names the analyst typed, where there is no doubt.

    A name that matches no active player, or two of them, resolves to nothing and the
    row keeps the name with a null id: the pages can still render "who was traded", and
    nobody is credited with a player they never held. The cache is keyed by the
    normalized name because the file spells the same player several ways across five
    seasons and the directory is a few thousand rows.
    """

    def __init__(self, players: list[Player]) -> None:
        self._players = players
        self._cache: dict[str, str | None] = {}

    def id_for(self, name: str) -> str | None:
        key = normalize_name(name)
        if key not in self._cache:
            try:
                self._cache[key] = _resolve_player(name, self._players)
            except Unresolved:
                self._cache[key] = None
        return self._cache[key]


def build_label_index(members: list[MemberRef]) -> dict[str, int | None]:
    """Map every normalized label a member may be called by to their id.

    The Sleeper username, the display name Sleeper shows, the published nickname and
    every private alias all point at the same member, because the analyst wrote whichever
    one was in his head. A label two members share maps to ``AMBIGUOUS``: the catalog
    would rather record an unresolved party than attribute a trade to the wrong person.
    """
    index: dict[str, int | None] = {}
    for member in members:
        labels = [*member.aliases, member.display_name, member.nickname]
        labels.append(member.sleeper_display_name)
        for label in labels:
            key = normalize_name(label or "")
            if not key:
                continue
            if key in index and index[key] != member.member_id:
                index[key] = AMBIGUOUS
            else:
                index.setdefault(key, member.member_id)
    return index


def resolve_parties(names: list[str], index: dict[str, int | None]) -> tuple[list[int], int]:
    """Resolve party nicknames to member ids, counting the ones that did not resolve.

    Order is the record's own, deduplicated, because a party list is a set of people.
    """
    resolved: list[int] = []
    unresolved = 0
    for name in names:
        member_id = index.get(normalize_name(str(name or "")), AMBIGUOUS)
        if member_id is None:
            unresolved += 1
            continue
        if member_id not in resolved:
            resolved.append(member_id)
    return resolved, unresolved


def _whole(value: Any) -> int | None:
    """A whole number, or nothing. ``True`` is not a 1 however much Python says so."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _week_and_date(value: Any) -> tuple[int | None, date | None]:
    """`week_or_date` carries both; the table keeps them in two columns.

    A week the analyst wrote in words ("Pre-Draft") is not a week number, so it is
    dropped and the date carries the row.
    """
    if not isinstance(value, dict):
        return None, None
    week = _whole(value.get("week"))
    text = value.get("date")
    if not isinstance(text, str):
        return week, None
    try:
        return week, date.fromisoformat(text.strip()[:10])
    except ValueError:
        return week, None


def _player_assets(assets: dict[str, Any], players: PlayerIndex) -> list[dict[str, Any]]:
    """`players` and `positions` are parallel lists; pair them up by position."""
    names = assets.get("players") or []
    positions = assets.get("positions") or []
    built: list[dict[str, Any]] = []
    for i, raw in enumerate(names):
        name = str(raw).strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            continue
        position = positions[i] if i < len(positions) else None
        built.append({
            "kind": "player",
            "sleeper_player_id": players.id_for(name),
            "name": name,
            # A closed vocabulary, so a stray note in the positions list cannot ride along.
            "position": position if position in SKILL_POSITIONS else None,
        })
    return built


def _faab_assets(assets: dict[str, Any]) -> list[dict[str, Any]]:
    """Every FAAB figure that changed hands. Zero is not an asset, and neither is "12"."""
    return [
        {"kind": "faab", "amount": amount}
        for raw in assets.get("faab") or []
        if (amount := _whole(raw)) is not None and amount > 0
    ]


def _condition_assets(assets: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Map the standard return-condition phrasings onto labels; count what was dropped.

    A record often says the same thing twice ("1 week", "one week hold"), so the labels
    are deduplicated: the table records that a trade was a one-week rental, not how many
    ways the chat said so.
    """
    built: list[dict[str, Any]] = []
    seen: set[str] = set()
    unmapped = 0
    for raw in assets.get("return_conditions") or []:
        label = CONDITION_PHRASES.get(normalize_name(str(raw)))
        if label is None:
            unmapped += 1
            continue
        if label in seen:
            continue
        seen.add(label)
        built.append({"kind": "condition", "label": label})
    return built, unmapped


def read_record(
    record: dict[str, Any],
    index: dict[str, int | None],
    players: PlayerIndex,
    season_id: int | None,
    loaded_at: datetime,
) -> CatalogReading:
    """Build one public row from one classification record."""
    picked = {key: record.get(key) for key in CATALOG_FIELDS}
    week, occurred_on = _week_and_date(picked["week_or_date"])
    parties = list(picked["parties"] or [])
    member_ids, unresolved = resolve_parties(parties, index)

    raw_assets = picked["assets"] if isinstance(picked["assets"], dict) else {}
    conditions, unmapped = _condition_assets(raw_assets)
    assets = _player_assets(raw_assets, players) + _faab_assets(raw_assets) + conditions

    confidence = picked["confidence"] if picked["confidence"] in CONFIDENCE_VALUES else "low"
    return CatalogReading(
        row=CatalogRow(
            catalog_id=str(picked["id"]),
            season=int(picked["season"]),
            season_id=season_id,
            week=week,
            occurred_on=occurred_on,
            # `type` and `structure` are the analyst's own vocabulary and stay his: the
            # taxonomy is still growing, and a column that refused a new kind of deal
            # would drop the deal rather than learn the word.
            trade_type=str(picked["type"] or "trade"),
            structure=str(picked["structure"] or "unknown"),
            party_member_ids=member_ids,
            party_count=len(parties),
            assets=assets,
            faab_total=_whole(picked["faab_total"]),
            confidence=confidence,
            unresolved_parties=unresolved,
            loaded_at=loaded_at,
        ),
        unmapped_conditions=unmapped,
    )
