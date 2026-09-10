"""What one run leaves behind, in the two tables the foundation built for it.

``public.survival_snapshots`` was specified for "timestamped team position and
survival estimates with model/input version" and ``public.recaps`` for "generated
daily or weekly posts and their publication state"; neither had a writer until
now, and neither needs a column added. Both are public and anon-readable, so
every value written here is public league data: a label, a score, an estimate.

Every method runs on the caller's connection and inside the caller's
transaction; none of them commit.
"""

from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.summary.models import EodSnapshot, SurvivalResult

PROJECTION_SOURCE = "sleeper"
#: ``recaps.state_version`` is for a corrected week's re-issue. A summary is never
#: corrected -- the next night's post supersedes it -- so every row is version 1.
RECAP_STATE_VERSION = 1


def results_payload(snapshot: EodSnapshot, result: SurvivalResult) -> list[dict]:
    """One entry per live team, in board order, as plain JSON values."""
    rows: list[dict] = []
    for team in snapshot.teams:
        odds = result.teams.get(team.team_id)
        if odds is None:
            continue
        rows.append(
            {
                "team_id": team.team_id,
                "label": team.label,
                "points": float(team.points),
                "projected_final": float(odds.projected_final),
                "pending": odds.pending,
                "adverse_event": odds.adverse_event,
                "probability": float(odds.probability),
                "is_estimated": odds.is_estimated,
            }
        )
    return rows


class SummaryRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record_snapshot(
        self,
        season_id: int,
        week: int,
        window: str,
        snapshot: EodSnapshot,
        result: SurvivalResult,
        now: datetime,
    ) -> bool:
        """Insert the run's snapshot; ``False`` when the same inputs were already
        recorded under the same window and model, which is the natural key."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.survival_snapshots
                  (season_id, week, game_window, snapshot_at, projection_source,
                   model_version, simulations, input_hash, results)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, week, game_window, input_hash, model_version)
                  do nothing
                returning id
                """,
                (
                    season_id,
                    week,
                    window,
                    now,
                    PROJECTION_SOURCE,
                    result.model_version,
                    result.simulations,
                    result.input_hash,
                    Jsonb(results_payload(snapshot, result)),
                ),
            )
            return cur.fetchone() is not None

    def record_recap(
        self,
        season_id: int,
        week: int,
        kind: str,
        prompt_version: str,
        facts_hash: str,
        body: str,
    ) -> int:
        """Record the composed message as a draft, returning the row's id.

        Keyed by the facts, so a rerun over the same facts lands on the same row
        and keeps the first body: what the chat was actually sent is the record,
        not whatever a later rehearsal composed over it.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.recaps
                  (season_id, week, recap_kind, state_version, prompt_version, facts_hash,
                   body, publication_state)
                values (%s, %s, %s, %s, %s, %s, %s, 'draft')
                on conflict (season_id, week, recap_kind, state_version, prompt_version,
                             facts_hash)
                  do update set recap_kind = excluded.recap_kind
                returning id
                """,
                (season_id, week, kind, RECAP_STATE_VERSION, prompt_version, facts_hash, body),
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("insert returned no id")
            return int(row[0])

    def mark_sent(self, recap_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "update public.recaps set publication_state = 'sent' where id = %s",
                (recap_id,),
            )

    def sent_today(self, season_id: int, week: int, kind: str) -> bool:
        """Has a recap of this kind -- ``eod:<local date>`` -- already gone out?"""
        with self._conn.cursor() as cur:
            cur.execute(
                "select 1 from public.recaps where season_id = %s and week = %s"
                " and recap_kind = %s and publication_state = 'sent' limit 1",
                (season_id, week, kind),
            )
            return cur.fetchone() is not None

    def set_input_version(self, run_id: int, version: str) -> None:
        """Stamp the run with what produced it, where ``ug ops audit-runs`` reads it.

        ``run_scheduled`` finishes the run with ``coalesce(null, input_version)``,
        so a version written here from inside the action survives the finish.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "update private.agent_runs set input_version = %s where id = %s",
                (version, run_id),
            )
