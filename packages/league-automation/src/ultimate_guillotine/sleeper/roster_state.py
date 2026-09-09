"""Derivations from one Sleeper roster payload, and the tables they land in.

Slot classification, FAAB and record recombination, and the elimination
precedence rule all live here as functions over plain values, so every rule the
spec states has a test that needs no database and no network. The three
repositories underneath them are the only writers of ``public.roster_holdings``
and ``public.team_season_state``, and of the cached league settings on
``public.seasons``; each runs in the caller's transaction and decides nothing.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.sleeper.models import SleeperLeague, SleeperRoster

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
    produces no row at all -- there is nobody to record. Every id yields at most
    one holding: an id repeated inside ``starters`` keeps its first (lowest-index)
    slot, and a later list never re-claims an id an earlier one already took.
    """
    # Starter-slot and empty-slot counts are not derived here: Task 9 derives them
    # from the database rather than from this payload.
    holdings: list[Holding] = []
    seen: set[str] = set()
    for index, player_id in enumerate(roster.starters):
        if not player_id or player_id == EMPTY_SLOT or player_id in seen:
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


def _whole(settings: dict[str, object], key: str) -> Decimal:
    """The whole part of a points value, exactly.

    Sleeper normally sends an integer, but some payloads carry the whole points
    as a float already holding the fraction (``"fpts": 312.45``). Truncating that
    to an ``int`` would silently drop hundredths, so it is read through
    ``Decimal(str(value))``, which keeps the digits the payload actually showed.
    """
    value = settings.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return Decimal(0)
    return Decimal(str(value)) if isinstance(value, float) else Decimal(value)


def _recombine(settings: dict[str, object], whole_key: str, decimal_key: str) -> Decimal:
    """Sleeper splits fantasy points into two integers; put them back together.

    The hundredths are a magnitude, not a signed addend: they carry the sign of
    the whole part, so ``fpts_against = -12`` with ``fpts_against_decimal = 5``
    is ``-12.05``, not ``-11.95``.
    """
    whole = _whole(settings, whole_key)
    hundredths = Decimal(abs(_int(settings, decimal_key))) / Decimal(100)
    return whole - hundredths if whole < 0 else whole + hundredths


def team_state_from_roster(roster: SleeperRoster, waiver_budget: int | None) -> TeamState:
    """Record, points, and FAAB for one team, from the roster's settings block.

    ``faab_used`` is clamped into ``[0, faab_budget]``. A league with no waiver
    budget still reports a per-roster ``waiver_budget_used``, and reporting more
    spent than the league ever offered would show a negative remaining balance.
    """
    settings = roster.settings
    budget = int(waiver_budget or 0)
    return TeamState(
        faab_budget=budget,
        faab_used=min(max(_int(settings, "waiver_budget_used"), 0), budget),
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
    """Keep the higher-ranked source. The Weekly Adjudicator is authoritative.

    Elimination is one-way for inference: clearing the Sleeper ``eliminated`` tag
    makes ``infer_elimination`` return ``Elimination.none()``, whose source is
    ``None`` and therefore outranked by any stored record -- so a stored
    ``sleeper_inferred`` elimination is never un-eliminated by the tag going away.
    Only a ``manual`` or ``adjudicator`` record can reverse an elimination.

    An unrecognised stored source ranks 0, the lowest: an unknown provenance
    yields to a known one rather than raising mid-sync.

    A same-ranked source never re-dates an elimination that already happened: a
    roster still carrying Ben's tag in week 5 was eliminated in week 3, and
    letting the equal-ranked incoming record win would re-stamp
    ``eliminated_week`` (and churn ``state_version``) on every sync. The first
    record of an elimination is the one that stands until a *higher* source
    replaces it.
    """
    if stored is None:
        return incoming
    incoming_rank = _SOURCE_RANK.get(incoming.source, 0)
    stored_rank = _SOURCE_RANK.get(stored.source, 0)
    if incoming_rank == stored_rank and stored.is_eliminated:
        return stored
    if incoming_rank >= stored_rank:
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


class SeasonSettingsRepository:
    """The league's own settings, cached on the season row."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def cache(self, season_id: int, league: SleeperLeague, now: datetime) -> None:
        """Cache the league's scoring rules on the season row, refreshed every sync."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update public.seasons
                set scoring_settings = %s, roster_positions = %s, waiver_budget = %s,
                    league_synced_at = %s
                where id = %s
                """,
                (
                    Jsonb(league.scoring_settings),
                    Jsonb(league.roster_positions),
                    league.waiver_budget,
                    now,
                    season_id,
                ),
            )


class RosterHoldingRepository:
    """Who a team holds right now. A cache of Sleeper, so it deletes."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_for_team(
        self, season_id: int, team_id: int, holdings: tuple[Holding, ...], now: datetime
    ) -> int:
        """Upsert every holding, then delete the ones this team no longer has.

        The delete is what makes a dropped player vanish. It runs in the caller's
        transaction, alongside the upserts, so the board never sees a roster with
        both the old and the new player on it.

        ``holdings`` -- not the roster's ``players`` list -- is what the delete
        keeps: ``classify_holdings`` treats ``starters`` as authoritative, so a
        started player Sleeper left out of ``players`` still has a row here, and
        deleting by ``players`` would evict him a moment after writing him.
        """
        with self._conn.cursor() as cur:
            if holdings:
                cur.executemany(
                    """
                    insert into public.roster_holdings
                      (season_id, team_id, sleeper_player_id, slot, slot_index,
                       lineup_position, synced_at)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    on conflict (season_id, team_id, sleeper_player_id) do update set
                      slot = excluded.slot, slot_index = excluded.slot_index,
                      lineup_position = excluded.lineup_position,
                      synced_at = excluded.synced_at
                    """,
                    [
                        (
                            season_id,
                            team_id,
                            holding.sleeper_player_id,
                            holding.slot,
                            holding.slot_index,
                            holding.lineup_position,
                            now,
                        )
                        for holding in holdings
                    ],
                )
            cur.execute(
                """
                delete from public.roster_holdings
                where season_id = %s and team_id = %s
                  and not (sleeper_player_id = any(%s))
                """,
                (season_id, team_id, [holding.sleeper_player_id for holding in holdings]),
            )
        return len(holdings)


class TeamStateRepository:
    """FAAB, record, points, and the elimination fact for one team-season."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def get_elimination(self, season_id: int, team_id: int) -> Elimination | None:
        """The stored elimination, or None when this team has no state row yet."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select is_eliminated, eliminated_week, elimination_source "
                "from public.team_season_state where season_id = %s and team_id = %s",
                (season_id, team_id),
            )
            row = cur.fetchone()
        return Elimination(*row) if row else None

    def upsert(
        self,
        season_id: int,
        team_id: int,
        state: TeamState,
        elimination: Elimination,
        now: datetime,
        bump_version: bool,
    ) -> None:
        """Write the team's state, bumping ``state_version`` only when told to.

        ``bump_version`` comes from ``bumps_state_version``: FAAB and points move
        every sync and are not a version-worthy change, so only a changed
        elimination fact advances the counter a consumer watches.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.team_season_state
                  (season_id, team_id, faab_budget, faab_used, wins, losses, ties,
                   points_for, points_against, is_eliminated, eliminated_week,
                   elimination_source, synced_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, team_id) do update set
                  faab_budget = excluded.faab_budget, faab_used = excluded.faab_used,
                  wins = excluded.wins, losses = excluded.losses, ties = excluded.ties,
                  points_for = excluded.points_for,
                  points_against = excluded.points_against,
                  is_eliminated = excluded.is_eliminated,
                  eliminated_week = excluded.eliminated_week,
                  elimination_source = excluded.elimination_source,
                  state_version = public.team_season_state.state_version + %s,
                  synced_at = excluded.synced_at
                """,
                (
                    season_id,
                    team_id,
                    state.faab_budget,
                    state.faab_used,
                    state.wins,
                    state.losses,
                    state.ties,
                    state.points_for,
                    state.points_against,
                    elimination.is_eliminated,
                    elimination.eliminated_week,
                    elimination.source,
                    now,
                    1 if bump_version else 0,
                ),
            )
