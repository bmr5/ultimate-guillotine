"""Pure derivations from one Sleeper roster payload.

Slot classification, FAAB and record recombination, and the elimination
precedence rule all live here as functions over plain values, so every rule the
spec states has a test that needs no database and no network.
"""

from dataclasses import dataclass
from decimal import Decimal

from ultimate_guillotine.sleeper.models import SleeperRoster

#: Sleeper writes the string "0" into a starter slot the manager left blank.
EMPTY_SLOT = "0"

#: Precedence, lowest to highest. An inferred elimination never overwrites a ruled one.
_SOURCE_RANK = {None: 0, "sleeper_inferred": 1, "manual": 2, "adjudicator": 3}


@dataclass(frozen=True)
class Holding:
    sleeper_player_id: str
    slot: str
    slot_index: int | None
    lineup_position: str | None


@dataclass(frozen=True)
class RosterClassification:
    holdings: tuple[Holding, ...]


def classify_holdings(roster: SleeperRoster, roster_positions: list[str]) -> RosterClassification:
    """Split a roster into starter / ir / taxi / bench rows, as Sleeper reports them.

    An id in ``starters`` is a starter, in ``reserve`` is ``ir``, in ``taxi`` is
    ``taxi``, and anything else in ``players`` is bench. A blank starter slot
    produces no row at all -- there is nobody to record.
    """
    # Starter-slot and empty-slot counts are not derived here: Task 9 derives them
    # from the database rather than from this payload.
    holdings: list[Holding] = []
    seen: set[str] = set()
    for index, player_id in enumerate(roster.starters):
        if not player_id or player_id == EMPTY_SLOT:
            continue
        position = roster_positions[index] if index < len(roster_positions) else None
        holdings.append(Holding(player_id, "starter", index, position))
        seen.add(player_id)
    for slot, ids in (("ir", roster.reserve), ("taxi", roster.taxi), ("bench", roster.players)):
        for player_id in ids:
            if not player_id or player_id == EMPTY_SLOT or player_id in seen:
                continue
            holdings.append(Holding(player_id, slot, None, None))
            seen.add(player_id)
    return RosterClassification(tuple(holdings))


@dataclass(frozen=True)
class TeamState:
    faab_budget: int
    faab_used: int
    wins: int
    losses: int
    ties: int
    points_for: Decimal
    points_against: Decimal


def _int(settings: dict[str, object], key: str) -> int:
    value = settings.get(key)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _recombine(settings: dict[str, object], whole_key: str, decimal_key: str) -> Decimal:
    """Sleeper splits fantasy points into two integers; put them back together."""
    whole = Decimal(_int(settings, whole_key))
    hundredths = Decimal(_int(settings, decimal_key))
    return whole + hundredths / Decimal(100)


def team_state_from_roster(roster: SleeperRoster, waiver_budget: int | None) -> TeamState:
    """Record, points, and FAAB for one team, from the roster's settings block."""
    settings = roster.settings
    return TeamState(
        faab_budget=int(waiver_budget or 0),
        faab_used=_int(settings, "waiver_budget_used"),
        wins=_int(settings, "wins"),
        losses=_int(settings, "losses"),
        ties=_int(settings, "ties"),
        points_for=_recombine(settings, "fpts", "fpts_decimal"),
        points_against=_recombine(settings, "fpts_against", "fpts_against_decimal"),
    )


@dataclass(frozen=True)
class Elimination:
    is_eliminated: bool
    eliminated_week: int | None
    source: str | None

    @classmethod
    def none(cls) -> "Elimination":
        return cls(False, None, None)


def infer_elimination(roster: SleeperRoster, week: int | None) -> Elimination:
    """Provisional elimination from a Sleeper roster tag Ben sets by hand.

    Deliberately narrow: only an explicit ``metadata.eliminated`` tag counts.
    Absence from ``get_matchups`` is not read as elimination, because whether an
    eliminated roster stays in Sleeper is still an open question for Ben, and a
    wrong guess would silently eliminate live teams.
    """
    tag = roster.metadata.get("eliminated")
    tagged = tag is True or (isinstance(tag, str) and tag.strip().lower() in {"true", "1", "yes"})
    if not tagged:
        return Elimination.none()
    return Elimination(True, week, "sleeper_inferred")


def merge_elimination(stored: Elimination | None, incoming: Elimination) -> Elimination:
    """Keep the higher-ranked source. The Weekly Adjudicator is authoritative."""
    if stored is None:
        return incoming
    if _SOURCE_RANK[incoming.source] >= _SOURCE_RANK[stored.source]:
        return incoming
    return stored


def bumps_state_version(stored: Elimination | None, merged: Elimination) -> bool:
    """Did the elimination fact itself change? A new source alone does not count."""
    if stored is None:
        return False
    return (stored.is_eliminated, stored.eliminated_week) != (
        merged.is_eliminated,
        merged.eliminated_week,
    )
