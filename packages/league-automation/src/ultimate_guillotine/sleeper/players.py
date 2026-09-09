"""Player directory: load Sleeper's player dump and sync it into ``public.players``.

Only active skill-position players (and defenses) are kept -- offensive
linemen, inactive/retired players, and anyone else outside ``SKILL_POSITIONS``
are dropped before they ever reach the database.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


@dataclass(frozen=True)
class Player:
    sleeper_player_id: str
    full_name: str
    position: str | None
    team: str | None
    active: bool


def load_players(raw: dict[str, dict[str, Any]]) -> list[Player]:
    players: list[Player] = []
    for pid, rec in raw.items():
        position = rec.get("position")
        if position not in SKILL_POSITIONS or not rec.get("active", False):
            continue
        name = rec.get("full_name") or " ".join(
            p for p in (rec.get("first_name"), rec.get("last_name")) if p
        )
        if not name:
            continue
        players.append(Player(str(pid), name, position, rec.get("team"), True))
    return players


class PlayerRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def upsert_many(self, players: list[Player], now: datetime) -> int:
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.players
                  (sleeper_player_id, full_name, position, team, active, synced_at)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (sleeper_player_id) do update set
                  full_name = excluded.full_name, position = excluded.position,
                  team = excluded.team, active = excluded.active, synced_at = excluded.synced_at
                """,
                [(p.sleeper_player_id, p.full_name, p.position, p.team, p.active, now)
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
                "select sleeper_player_id, full_name, position, team, active "
                "from public.players where active order by full_name"
            )
            return [Player(*row) for row in cur.fetchall()]

    def last_synced_at(self) -> datetime | None:
        with self._conn.cursor() as cur:
            cur.execute("select max(synced_at) from public.players")
            row = cur.fetchone()
            return row[0] if row else None


def sync_players(client, conn, now: datetime) -> int:
    """Refresh ``public.players`` from Sleeper, returning how many were written.

    Players the feed no longer carries are marked inactive rather than deleted,
    in the same transaction: the directory has to shrink as people retire, and
    the ids stay resolvable for the trades that already name them.
    """
    players = load_players(client.get_players())
    repo = PlayerRepository(conn)
    with conn.transaction():
        written = repo.upsert_many(players, now)
        repo.deactivate_missing([p.sleeper_player_id for p in players], now)
    return written
