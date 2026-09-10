"""The auction, from Sleeper's draft feed into ``public.draft_picks``.

Spec: docs/superpowers/specs/2026-09-10-player-card-design.md. The feed is
``/draft/{id}/picks``: one record per pick with ``pick_no``, ``round``,
``draft_slot``, ``roster_id``, ``player_id`` and ``metadata.amount`` as a string.
The draft record itself (``/draft/{id}``) says whether the auction is over and how
big it was, which is what the guards below check the payload against.

Shaped like ``scores.py``: fetch first, parse with a pure loader, upsert on a
natural key inside the transaction ``run_scheduled`` already holds. Unlike the
scores, a rerun writes the same rows -- the draft is a fact, not a live number --
so the daily fire exists only so a pick Sleeper corrects reaches the board without
anyone remembering.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.models import SleeperDraft
from ultimate_guillotine.sleeper.teams import teams_by_roster_id
from ultimate_guillotine.sleeper.values import as_int


@dataclass(frozen=True)
class DraftPick:
    """One auction pick, already mapped off Sleeper's roster id onto a team id."""

    team_id: int
    sleeper_player_id: str
    sleeper_draft_id: str
    pick_no: int
    round: int
    draft_slot: int
    #: The position Sleeper recorded on the pick -- what the auction ranked by.
    position: str | None
    amount: int


@dataclass(frozen=True)
class DraftReport:
    """What one ``ug sleeper draft`` run wrote. Counts only, never a name."""

    picks: int
    #: The draft's Sleeper status. Anything but ``complete`` means nothing was written.
    status: str

    @property
    def skipped(self) -> bool:
        return self.status != "complete"


def _amount(record: dict[str, Any]) -> int | None:
    """The auction price, or None when the pick carries no usable one.

    Sleeper sends it as a string inside ``metadata``. Zero is not a price: an
    auction pick costs at least a dollar, so ``"0"`` reads as missing.
    """
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        return None
    amount = as_int(metadata.get("amount"))
    return amount if amount is not None and amount >= 1 else None


def load_draft_picks(
    draft: SleeperDraft,
    payload: list[dict[str, Any]],
    team_by_roster_id: dict[int, int],
) -> list[DraftPick]:
    """Parse the picks payload into rows, or refuse it.

    Every guard raises rather than skipping. A partial auction on the board would
    look exactly like a finished one, and the mark beside a player's name would be
    silently wrong for everyone the payload dropped -- so the run fails, the last
    good rows stand, and the ops note says why.
    """
    if not payload:
        raise ValueError(f"sleeper returned no picks for draft {draft.draft_id}")
    expected = (draft.teams or 0) * (draft.rounds or 0)
    if len(payload) < expected:
        raise ValueError(
            f"draft {draft.draft_id}: {len(payload)} picks, expected at least {expected}"
        )
    picks: list[DraftPick] = []
    for record in payload:
        if not isinstance(record, dict):
            raise TypeError(f"draft {draft.draft_id}: a pick is not an object")
        pick_no = as_int(record.get("pick_no"))
        round_no = as_int(record.get("round"))
        slot = as_int(record.get("draft_slot"))
        roster_id = as_int(record.get("roster_id"))
        player_id = record.get("player_id")
        if (
            pick_no is None
            or round_no is None
            or slot is None
            or roster_id is None
            or not isinstance(player_id, str)
            or not player_id
        ):
            raise ValueError(
                f"draft {draft.draft_id}: pick {record.get('pick_no')} is malformed"
            )
        amount = _amount(record)
        if amount is None:
            raise ValueError(f"draft {draft.draft_id}: pick {pick_no} has no auction amount")
        team_id = team_by_roster_id.get(roster_id)
        if team_id is None:
            raise ValueError(
                f"draft {draft.draft_id}: roster {roster_id} has no team row; "
                f"run ug sleeper sync"
            )
        metadata = record.get("metadata")
        position = metadata.get("position") if isinstance(metadata, dict) else None
        picks.append(
            DraftPick(
                team_id=team_id,
                sleeper_player_id=player_id,
                sleeper_draft_id=draft.draft_id,
                pick_no=pick_no,
                round=round_no,
                draft_slot=slot,
                position=position if isinstance(position, str) and position else None,
                amount=amount,
            )
        )
    return picks


class DraftRepository:
    """Writes for the season's auction. Runs on the caller's connection and transaction."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_many(
        self,
        season_id: int,
        picks: list[DraftPick],
        drafted_at: datetime,
        now: datetime,
    ) -> int:
        """Write one row per pick, keyed on ``(season_id, sleeper_player_id)``.

        A player is auctioned once a season, so that is the conflict target. The
        second unique key, ``(season_id, sleeper_draft_id, pick_no)``, is a guard
        rather than a target: a pick Sleeper reassigns to a different player would
        trip it and fail the run loudly, which is right -- nothing here may delete
        the stale row, so a human has to look.
        """
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.draft_picks
                  (season_id, team_id, sleeper_player_id, sleeper_draft_id, pick_no, round,
                   draft_slot, position, amount, drafted_at, synced_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, sleeper_player_id) do update set
                  team_id = excluded.team_id,
                  sleeper_draft_id = excluded.sleeper_draft_id,
                  pick_no = excluded.pick_no,
                  round = excluded.round,
                  draft_slot = excluded.draft_slot,
                  position = excluded.position,
                  amount = excluded.amount,
                  drafted_at = excluded.drafted_at,
                  synced_at = excluded.synced_at
                """,
                [
                    (
                        season_id,
                        pick.team_id,
                        pick.sleeper_player_id,
                        pick.sleeper_draft_id,
                        pick.pick_no,
                        pick.round,
                        pick.draft_slot,
                        pick.position,
                        pick.amount,
                        drafted_at,
                        now,
                    )
                    for pick in picks
                ],
            )
        return len(picks)


def sync_draft(
    client: SleeperClient,
    conn: psycopg.Connection,
    league_id: str,
    season_id: int,
    now: datetime,
) -> DraftReport:
    """Fetch the league's canonical draft and, once it is complete, write its picks.

    Three fetches before any write. A draft that is not ``complete`` is a no-op that
    reports ``skipped`` -- before the auction the job has nothing to say. The
    payload then has to pass ``load_draft_picks`` or the run fails with the last
    good rows untouched.
    """
    league = client.get_league(league_id)
    if not league.draft_id:
        raise ValueError(f"league {league_id} names no draft")
    draft = client.get_draft(league.draft_id)
    if draft.status != "complete":
        return DraftReport(picks=0, status=draft.status)
    drafted_at = draft.started_at
    if drafted_at is None:
        raise ValueError(f"draft {draft.draft_id} has no start time")
    payload = client.get_draft_picks(draft.draft_id)
    picks = load_draft_picks(draft, payload, teams_by_roster_id(conn, season_id))
    DraftRepository(conn).upsert_many(season_id, picks, drafted_at, now)
    return DraftReport(picks=len(picks), status=draft.status)
