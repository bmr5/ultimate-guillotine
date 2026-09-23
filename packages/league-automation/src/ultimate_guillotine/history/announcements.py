"""Short, confirmed cut and gulag announcements using the existing durable message delivery."""

import logging
from collections.abc import Callable

from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.core.signature import BOT_SIGNATURE
from ultimate_guillotine.data.repositories import (
    OutboundRepository,
    RunRepository,
    TargetRepository,
)
from ultimate_guillotine.history.adjudicator import Unresolved, expected_remaining
from ultimate_guillotine.history.archive_jobs import configuration
from ultimate_guillotine.history.archive_store import digest, latest_weeks, rows
from ultimate_guillotine.messages.delivery import DeliveryService

AGENT = "archive-cuts"
log = logging.getLogger(__name__)


class LocalDeliveryNotes:
    def feed(self, text: str) -> None:
        # The requested destination is the league chat; retain diagnostics locally.
        log.info("%s", text)


def build_cut_delivery(deps):
    return DeliveryService(
        deps.settings,
        deps.client,
        TargetRepository(deps.conn),
        OutboundRepository(deps.conn),
        LocalDeliveryNotes(),
        commit=deps.conn.commit,
    )


def cut_message(
    week: int, remaining: int, cuts: list[dict], qualifiers: list[dict], *, correction: bool
) -> str:
    expected = (18 if week == 1 else expected_remaining(week - 1)) - expected_remaining(week)
    if len(cuts) != expected or len({c["team_id"] for c in cuts}) != expected:
        raise Unresolved("confirmed cut bundle has an unexpected team count")
    if remaining != expected_remaining(week):
        raise Unresolved("confirmed cut bundle has an unexpected survivor count")
    expected_qualifiers = 2 if week <= 11 else 0
    if (
        len(qualifiers) != expected_qualifiers
        or len({q["team_id"] for q in qualifiers}) != expected_qualifiers
        or any(q["contest_week"] != week + 1 for q in qualifiers)
        or {q["team_id"] for q in qualifiers} & {c["team_id"] for c in cuts}
    ):
        raise Unresolved("confirmed gulag bundle has invalid qualifiers")
    prefix = "Correction: " if correction else ""

    def names(teams):
        return " and ".join(
            " ".join((t["manager_label"] or t["team_label"]).split()) for t in teams
        )

    if not cuts:
        content = f"{prefix}Week {week}: Nobody was cut. All {remaining} teams remain alive."
    else:
        content = (
            f"{prefix}Week {week} {'cut' if len(cuts) == 1 else 'cuts'}: {names(cuts)}."
            + f"\n{remaining} {'team remains' if remaining == 1 else 'teams remain'}."
        )
    if qualifiers:
        content += f"\nWeek {week + 1} gulag qualifiers: {names(qualifiers)}."
    return content


def announce_confirmed(conn, settings, delivery, *, commit: Callable | None = None) -> int:
    """Call after adjudication commits. A session lock survives delivery's commits.

    Failed sends reuse their original run id so delivery can reconcile a crash.
    Only changed cuts or gulag qualifiers warrant another announcement, not score-only revisions.
    """
    if settings.delivery_mode is not DeliveryMode.PRODUCTION:
        return 0
    config = configuration(conn)
    if not config or config["scope"] != "production":
        return 0
    persist = commit or conn.commit
    sid = config["season_id"]
    locked = conn.execute("select pg_try_advisory_lock(82426,%s)", (sid,)).fetchone()[0]
    if not locked:
        return 0
    count = 0
    runs = RunRepository(conn)
    try:
        expected_week = 1
        for record in latest_weeks(conn, sid, "production"):
            if record["week"] != expected_week or record["status"] != "confirmed":
                break
            expected_week += 1
            cuts = rows(
                conn,
                """select team_id,manager_label,team_label from public.team_event_snapshots
                where week_revision_id=%s and event_type='eliminated' order by team_id""",
                (record["id"],),
            )
            qualifiers = rows(
                conn,
                """select team_id,manager_label,team_label,contest_week
                from public.team_event_snapshots
                where week_revision_id=%s and event_type='gulag_qualified' order by team_id""",
                (record["id"],),
            )
            outcome_hash = digest(
                (
                    sorted(c["team_id"] for c in cuts),
                    record["remaining_teams"],
                    sorted((q["team_id"], q["contest_week"]) for q in qualifiers),
                )
            )
            prefix = f"archive-cuts:{sid}:{record['week']}:"
            previous = rows(
                conn,
                """select r.id,r.output_hash,r.status,o.state,o.content from private.agent_runs r
                join private.outbound_messages o on o.run_id=r.id
                join private.delivery_targets t on t.id=o.delivery_target_id
                where r.agent=%s and r.idempotency_key like %s
                and o.state in ('sending','sent','reconciled') and t.mode='production'
                order by o.id desc limit 1""",
                (AGENT, prefix + "%"),
            )
            same_outcome = previous and previous[0]["output_hash"] == outcome_hash
            if same_outcome and previous[0]["state"] != "sending":
                if previous[0]["status"] != "succeeded":
                    runs.finish(previous[0]["id"], "succeeded", output_hash=outcome_hash)
                    persist()
                continue
            content = cut_message(
                record["week"],
                record["remaining_teams"],
                cuts,
                qualifiers,
                correction=bool(previous),
            )
            if same_outcome:
                # A score-only revision can arrive after an ambiguous send. Reuse
                # the original text and run so delivery reconciles it without reposting.
                run_id = previous[0]["id"]
                content = previous[0]["content"].removesuffix("\n" + BOT_SIGNATURE)
            else:
                # Keep the original cuts-only run immutable when adding its missing gulag line.
                key = prefix + str(record["id"]) + ":gulag-v2"
                run_id = runs.reserve(AGENT, "cron", key)
                if run_id is None:
                    run_id = rows(
                        conn, "select id from private.agent_runs where idempotency_key=%s", (key,)
                    )[0]["id"]
            # Retain the outcome before sending, including a crash before runs.finish.
            conn.execute(
                "update private.agent_runs set output_hash=%s,status='running',error=null where id=%s",
                (outcome_hash, run_id),
            )
            persist()
            try:
                delivery.deliver(run_id, AGENT, content)
            except Exception as exc:
                runs.finish(
                    run_id, "failed", output_hash=outcome_hash, error=exc.__class__.__name__
                )
                persist()
                raise
            runs.finish(run_id, "succeeded", output_hash=outcome_hash)
            persist()
            count += 1
        return count
    finally:
        conn.execute("select pg_advisory_unlock(82426,%s)", (sid,))
        persist()
