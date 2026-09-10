"""Player directory: load Sleeper's player dump and sync it into ``public.players``.

Only active skill-position players (and defenses) are kept -- offensive
linemen, inactive/retired players, and anyone else outside ``SKILL_POSITIONS``
are dropped before they ever reach the database.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}

#: Every injury flag the players feed is known to emit, counted off the live dump on
#: 2026-09-09: ``Questionable`` 362, ``IR`` 198, ``NA`` 95, ``PUP`` 38, ``Out`` 21,
#: ``Sus`` 11, ``COV`` 2, ``DNR`` 2, ``Doubtful`` 1.
#:
#: The vocabulary lives here rather than in a check constraint on the column. A tenth
#: value is a thing Sleeper can start emitting on any Tuesday, and a constraint would
#: turn that into a failed sync -- the whole directory stuck on the last good rows,
#: including the flags for the nine values that are still perfectly good. So an unknown
#: value is read as *no flag* (the board never guesses a player out of a lineup) and
#: counted, and the count is surfaced by ``sync_players`` so it reaches ops as a note
#: rather than as an outage. The column comment still records the vocabulary.
KNOWN_INJURY_STATUSES: frozenset[str] = frozenset(
    {"Questionable", "Doubtful", "Out", "IR", "PUP", "Sus", "NA", "COV", "DNR"}
)


@dataclass(frozen=True)
class Player:
    sleeper_player_id: str
    full_name: str
    position: str | None
    team: str | None
    active: bool
    #: Sleeper's own flag, one of ``KNOWN_INJURY_STATUSES``, or ``None`` when the
    #: feed carries none -- the normal case for all but a few hundred records --
    #: or carries one this build has never heard of.
    injury_status: str | None = None


def _injury_status(rec: dict[str, Any]) -> tuple[str | None, str | None]:
    """Sleeper's injury flag as ``(status, unknown_value)``.

    The feed emits an empty string for at least one record, and an empty string is
    not an injury -- it is the same absence as a missing key. A value outside
    ``KNOWN_INJURY_STATUSES`` is read as no flag *and* returned as the second item,
    so the caller can count it: the board would otherwise render it as an unreadable
    tag, and treating it as an absence is the safe half of the guess -- it leaves the
    player in his lineup rather than reporting him out on a string nobody has read.
    """
    raw = rec.get("injury_status")
    if not isinstance(raw, str):
        return None, None
    status = raw.strip()
    if not status:
        return None, None
    if status not in KNOWN_INJURY_STATUSES:
        return None, status
    return status, None


@dataclass(frozen=True)
class PlayerLoad:
    """The players a dump yielded, and what could not be read off it."""

    players: list[Player]
    #: Injury flags outside ``KNOWN_INJURY_STATUSES``, by spelling and count. Empty on
    #: every run until Sleeper adds a value, which is the point of counting them.
    unknown_statuses: Counter[str] = field(default_factory=Counter)


def load_players_with_notes(raw: dict[str, dict[str, Any]]) -> PlayerLoad:
    """``load_players``, plus what the dump carried that this build cannot read."""
    players: list[Player] = []
    unknown: Counter[str] = Counter()
    for pid, rec in raw.items():
        position = rec.get("position")
        if position not in SKILL_POSITIONS or not rec.get("active", False):
            continue
        name = rec.get("full_name") or " ".join(
            p for p in (rec.get("first_name"), rec.get("last_name")) if p
        )
        if not name:
            continue
        status, unknown_status = _injury_status(rec)
        if unknown_status is not None:
            unknown[unknown_status] += 1
        players.append(Player(str(pid), name, position, rec.get("team"), True, status))
    return PlayerLoad(players, unknown)


def load_players(raw: dict[str, dict[str, Any]]) -> list[Player]:
    return load_players_with_notes(raw).players


class PlayerRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def upsert_many(self, players: list[Player], now: datetime) -> int:
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.players
                  (sleeper_player_id, full_name, position, team, active, injury_status,
                   synced_at)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (sleeper_player_id) do update set
                  full_name = excluded.full_name, position = excluded.position,
                  team = excluded.team, active = excluded.active,
                  -- Assigned unconditionally, so a recovered player loses last month's
                  -- flag: the column is current state, not a log.
                  injury_status = excluded.injury_status, synced_at = excluded.synced_at
                """,
                [(p.sleeper_player_id, p.full_name, p.position, p.team, p.active,
                  p.injury_status, now)
                 for p in players],
            )
        return len(players)

    def deactivate_missing(self, keep_ids: list[str], now: datetime) -> int:
        """Mark every active player outside ``keep_ids`` inactive, returning how
        many were changed.

        Sleeper drops retired and cut players from its dump. The rows are never
        deleted -- a trade recorded last season names a player id, and deleting
        it would orphan that record -- so they are flipped inactive instead and
        stop being offered to name resolution.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update public.players set active = false, synced_at = %s
                where active and not (sleeper_player_id = any(%s))
                """,
                (now, keep_ids),
            )
            return cur.rowcount

    def all_active(self) -> list[Player]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, full_name, position, team, active, injury_status "
                "from public.players where active order by full_name"
            )
            return [Player(*row) for row in cur.fetchall()]

    def last_synced_at(self) -> datetime | None:
        with self._conn.cursor() as cur:
            cur.execute("select max(synced_at) from public.players")
            row = cur.fetchone()
            return row[0] if row else None


@dataclass(frozen=True)
class PlayerSyncReport:
    """What one ``ug sleeper players`` run did, and the one thing worth a note."""

    written: int
    #: How many records carried an injury flag this build does not know. Zero on
    #: every ordinary run; anything else means Sleeper has changed its vocabulary
    #: and those players are being read as unflagged until it is added.
    unknown_statuses: int = 0
    #: The distinct spellings behind that count, sorted, so the note names them.
    unknown_values: tuple[str, ...] = ()


def sync_players(client, conn, now: datetime) -> PlayerSyncReport:
    """Refresh ``public.players`` from Sleeper, reporting what was written.

    Players the feed no longer carries are marked inactive rather than deleted,
    in the same transaction: the directory has to shrink as people retire, and
    the ids stay resolvable for the trades that already name them.

    An injury flag outside ``KNOWN_INJURY_STATUSES`` does not fail the run. It is
    stored as null -- no flag -- logged, and counted into the report, which is how
    it reaches ops: a tenth Sleeper status is a thing to go and read about, not a
    reason for the directory to stop updating.
    """
    load = load_players_with_notes(client.get_players())
    players = load.players
    if not players:
        # A thin 200 (empty dump, or nothing passing the position filter) must not
        # flip the whole directory inactive and turn every alert into a clarification.
        raise RuntimeError("sleeper returned no active skill players")
    unknown_values = tuple(sorted(load.unknown_statuses))
    unknown_total = sum(load.unknown_statuses.values())
    if unknown_total:
        log.warning(
            "sleeper injury statuses this build does not know: %s (%d records, read as no flag)",
            ", ".join(f"{value} x{load.unknown_statuses[value]}" for value in unknown_values),
            unknown_total,
        )
    repo = PlayerRepository(conn)
    with conn.transaction():
        written = repo.upsert_many(players, now)
        repo.deactivate_missing([p.sleeper_player_id for p in players], now)
    return PlayerSyncReport(written, unknown_total, unknown_values)
