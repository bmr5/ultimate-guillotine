"""Private evidence and atomic, revisioned publication for the season history tab."""

import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ultimate_guillotine.history.adjudicator import RULES_VERSION, Outcome, Unresolved


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def rows(conn: psycopg.Connection, sql: str, params=()) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def latest_weeks(conn, season_id: int, scope: str) -> list[dict]:
    return rows(
        conn,
        """select distinct on (week) * from public.season_history_weeks
        where season_id=%s and scope=%s order by week, revision desc""",
        (season_id, scope),
    )


def prior_state(conn, season_id: int, scope: str, week: int, team_ids: set[int]):
    alive = set(team_ids)
    qualifiers: tuple[int, ...] = ()
    versions = []
    history = {r["week"]: r for r in latest_weeks(conn, season_id, scope)}
    for number in range(1, week):
        record = history.get(number)
        if not record or record["status"] != "confirmed":
            raise Unresolved(f"week {number} is not finalized")
        events = rows(
            conn,
            "select * from public.team_event_snapshots where week_revision_id=%s",
            (record["id"],),
        )
        alive -= {e["team_id"] for e in events if e["event_type"] == "eliminated"}
        qualifiers = tuple(
            sorted(e["team_id"] for e in events if e["event_type"] == "gulag_qualified")
        )
        versions.append((number, record["input_hash"]))
    return alive, qualifiers, versions


def latest_ruling(conn, season_id: int, scope: str, week: int) -> dict:
    result = rows(
        conn,
        """select id, payload from private.archive_rulings
        where season_id=%s and scope=%s and week=%s order by id desc limit 1""",
        (season_id, scope, week),
    )
    return result[0] if result else {"id": None, "payload": {}}


def protection_contracts(conn, season_id: int, scope: str, week: int) -> list[dict]:
    # A registered protection asset does not establish when insurance was exercised.
    # Surface unassigned accepted agreements instead of guessing the participant.
    return rows(
        conn,
        """select t.trade_code, t.id, r.terms, r.id as revision_id
        from public.trades t join public.trade_revisions r on r.id=t.current_revision_id
        where t.season_id=%s and t.status='accepted' and t.trade_code not like 'TEST-%%'
        and (r.effective_week <= %s or (r.effective_week is null and t.created_at <= coalesce(
          (select first_complete_at from private.archive_week_jobs
           where season_id=%s and scope=%s and week=%s), 'infinity'::timestamptz)))
        and exists(select 1 from jsonb_array_elements(r.terms->'assets') a
                   where a->>'kind'='protection')""",
        (season_id, week, season_id, scope, week),
    )


def contract_assignments(conn, season_id: int, scope: str) -> dict[str, int]:
    # Each week's newest complete ruling replaces its earlier ruling.
    latest = rows(
        conn,
        """select distinct on (week) week, payload from private.archive_rulings
        where season_id=%s and scope=%s order by week, id desc""",
        (season_id, scope),
    )
    assigned: dict[str, int] = {}
    for record in latest:
        for code in record["payload"].get("reviewed_trade_codes", []):
            if code in assigned and assigned[code] != record["week"]:
                raise Unresolved("a protection agreement is assigned to multiple contests")
            assigned[code] = record["week"]
    return assigned


def contest_ruling(conn, season_id: int, scope: str, week: int):
    ruling = latest_ruling(conn, season_id, scope, week)
    for code, revision_id in ruling["payload"].get("reviewed_trade_revisions", {}).items():
        trade = rows(
            conn,
            "select current_revision_id,status from public.trades where season_id=%s and trade_code=%s",
            (season_id, code),
        )
        if (
            not trade
            or trade[0]["status"] != "accepted"
            or trade[0]["current_revision_id"] != revision_id
        ):
            raise Unresolved("A reviewed protection agreement changed; refresh the contest ruling")
    contracts = protection_contracts(conn, season_id, scope, week) if 2 <= week <= 12 else []
    assigned = contract_assignments(conn, season_id, scope) if contracts else {}
    unknown = [t["trade_code"] for t in contracts if t["trade_code"] not in assigned]
    if unknown:
        raise Unresolved("Protection agreements need a contest ruling: " + ", ".join(unknown))
    return ruling, contracts


def publish(
    conn,
    *,
    season_id: int,
    season: int,
    scope: str,
    week: int,
    status: str,
    input_hash: str,
    now: datetime,
    outcome: Outcome | None,
    evidence: dict | None,
    scores: dict[int, Decimal],
    matchup_by_team: dict[int, dict],
    entry_evidence: dict[int, dict] | None = None,
) -> int:
    """Caller holds a season lock and transaction; publication never sends notifications."""
    previous = rows(
        conn,
        """select id, revision, input_hash, status from public.season_history_weeks
        where season_id=%s and scope=%s and week=%s order by revision desc limit 1""",
        (season_id, scope, week),
    )
    if previous and previous[0]["input_hash"] == input_hash and previous[0]["status"] == status:
        return previous[0]["id"]
    revision = previous[0]["revision"] + 1 if previous else 1
    correction = status == "confirmed" and bool(
        rows(
            conn,
            "select id from public.season_history_weeks where season_id=%s and scope=%s and week=%s and status='confirmed' limit 1",
            (season_id, scope, week),
        )
    )
    result = conn.execute(
        """insert into public.season_history_weeks
        (season_id,season,week,revision,scope,status,remaining_teams,checked_at,rules_version,input_hash,is_correction)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        (
            season_id,
            season,
            week,
            revision,
            scope,
            status,
            len(outcome.alive) if outcome else None,
            now,
            RULES_VERSION,
            input_hash,
            correction,
        ),
    ).fetchone()
    revision_id = result[0]
    if scope == "production":
        # Superseding non-final rows withdraw prior final scores without deleting evidence.
        previous_scores = rows(
            conn,
            """select distinct on (team_id) team_id,points from public.weekly_results
            where season_id=%s and week=%s order by team_id,state_version desc""",
            (season_id, week),
        )
        version = conn.execute(
            "select coalesce(max(state_version),0)+1 from public.weekly_results where season_id=%s and week=%s",
            (season_id, week),
        ).fetchone()[0]
        current_scores = {r["team_id"]: r["points"] for r in previous_scores}
        if outcome:
            participating = set(outcome.alive) | {
                e.team for e in outcome.events if e.kind == "eliminated"
            }
            current_scores = {t: p for t, p in scores.items() if t in participating}
        for team_id, points in current_scores.items():
            conn.execute(
                """insert into public.weekly_results (season_id,week,team_id,points,state_version,is_final)
                values (%s,%s,%s,%s,%s,%s)""",
                (season_id, week, team_id, points, version, status == "confirmed"),
            )
        conn.execute(
            """insert into public.league_events
            (season_id,week,event_type,occurred_at,payload,idempotency_key)
            values (%s,%s,'weekly_adjudication',%s,%s,%s)""",
            (
                season_id,
                week,
                now,
                Jsonb({"revision": revision, "status": status, "week_revision_id": revision_id}),
                f"archive:{season_id}:{week}:{revision}",
            ),
        )
    if outcome is None or evidence is None:
        return revision_id
    all_teams = evidence["payload"]["teams"]
    for event in outcome.events:
        saved = (
            (entry_evidence or {}).get(event.team, evidence)
            if event.kind == "gulag_entered"
            else evidence
        )
        team = saved["payload"]["teams"][str(event.team)]
        qualifier = all_teams.get(str(event.qualifier))
        opponent = all_teams.get(str(event.opponent))
        observation_time = saved["observed_at"]
        # One observation gives complete contents, not a precise final-whistle timestamp.
        # If the pre-close observations were missed, coverage stays partial.
        coverage = saved.get("coverage", "partial")
        amount = team.get("faab_remaining")
        money_coverage = "missing" if amount is None else coverage
        matchup = matchup_by_team.get(event.team, {})
        event_score = scores.get(event.team)
        if event.kind == "gulag_entered":
            # Entry precedes this contest's scoring. Never attach its later score to the entry.
            event_score = None
        params = (
            revision_id,
            season_id,
            f"{week}:{event.kind}:{event.team}",
            event.kind,
            event.team,
            team["team_label"],
            team["manager_label"],
            event.contest_week - 1 if event.contest_week else None,
            event.contest_week,
            f"{season}:gulag:{event.contest_week}" if event.contest_week else None,
            event.qualifier,
            qualifier["team_label"] if qualifier else None,
            event.qualifier if event.qualifier != event.team else None,
            qualifier["team_label"] if qualifier and event.qualifier != event.team else None,
            event.reason,
            event_score,
            opponent["team_label"] if opponent else None,
            scores.get(event.opponent),
            amount,
            observation_time if amount is not None else None,
            observation_time,
            coverage,
            money_coverage,
            saved["id"],
        )
        snapshot_id = conn.execute(
            """insert into public.team_event_snapshots
            (week_revision_id,season_id,event_key,event_type,team_id,team_label,manager_label,
             qualification_week,contest_week,contest_id,qualifier_team_id,qualifier_label,
             beneficiary_team_id,beneficiary_label,elimination_reason,score,opponent_label,
             opponent_score,faab_remaining,money_as_of,effective_at,roster_coverage,money_coverage,
             source_observation_id)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            returning id""",
            params,
        ).fetchone()[0]
        saved_players = {p["player_id"]: p for p in team["players"]}
        lineup = team["starters"] if event.kind == "gulag_entered" else matchup.get("starters", [])
        points = {} if event.kind == "gulag_entered" else matchup.get("players_points", {})
        for player_id in dict.fromkeys(
            [*saved_players, *(str(p) for p in lineup if p and p != "0")]
        ):
            player = saved_players.get(player_id, {})
            # The directory label captured with the matchup is preferred to a later lookup.
            directory = evidence["payload"].get("directory", {}).get(player_id, {})
            point = points.get(player_id)
            if (
                isinstance(point, bool)
                or not isinstance(point, (int, float))
                or not math.isfinite(point)
            ):
                point = None
            conn.execute(
                """insert into public.team_event_players
                (snapshot_id,player_id,player_label,position,slot,started,owned_at_cutoff,keeper,points)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    snapshot_id,
                    player_id,
                    player.get("player_label", directory.get("full_name") or player_id),
                    player.get("position", directory.get("position")),
                    player.get("slot"),
                    player_id in lineup,
                    bool(player.get("owned", False)),
                    None,
                    point,
                ),
            )
    return revision_id


def invalidate_later(conn, season_id: int, season: int, scope: str, week: int, now: datetime):
    for record in latest_weeks(conn, season_id, scope):
        if record["week"] <= week or record["status"] == "retracted":
            continue
        publish(
            conn,
            season_id=season_id,
            season=season,
            scope=scope,
            week=record["week"],
            status="retracted",
            input_hash=digest(("dependency", week, record["input_hash"])),
            now=now,
            outcome=None,
            evidence=None,
            scores={},
            matchup_by_team={},
        )
        conn.execute(
            """update private.archive_week_jobs set status='pending', next_check_at=%s,
            candidate_hash=null, stable_since=null, published_hash=null,
            last_error='Earlier week changed; awaiting recalculation'
            where season_id=%s and scope=%s and week=%s""",
            (now, season_id, scope, record["week"]),
        )


def update_current_state(conn, season_id: int, scope: str):
    if scope != "production":
        return
    cuts: dict[int, int] = {}
    expected = 1
    for record in latest_weeks(conn, season_id, scope):
        if record["week"] != expected or record["status"] != "confirmed":
            break
        for event in rows(
            conn,
            """select team_id from public.team_event_snapshots
            where week_revision_id=%s and event_type='eliminated'""",
            (record["id"],),
        ):
            cuts[event["team_id"]] = record["week"]
        expected += 1
    for team in rows(conn, "select id from public.teams where season_id=%s", (season_id,)):
        cut_week = cuts.get(team["id"])
        conn.execute(
            """update public.team_season_state set
            state_version=state_version + case when (is_eliminated,eliminated_week)
                is distinct from (%s::boolean,%s::int) then 1 else 0 end,
            is_eliminated=%s, eliminated_week=%s, elimination_source='adjudicator'
            where season_id=%s and team_id=%s""",
            (cut_week is not None, cut_week, cut_week is not None, cut_week, season_id, team["id"]),
        )


def current_gulag_events(conn, season_id: int):
    """Current official pairing for the Daily, including an explicit unresolved marker."""
    available = conn.execute("select to_regclass('private.archive_seasons')").fetchone()[0]
    if available is None:
        return None
    config = rows(
        conn,
        "select scope from private.archive_seasons where season_id=%s and enabled",
        (season_id,),
    )
    if not config or config[0]["scope"] != "production":
        return None
    team_ids = {
        r["id"] for r in rows(conn, "select id from public.teams where season_id=%s", (season_id,))
    }
    result = []
    for week in range(2, 13):
        pair = ()
        try:
            alive, qualifiers, _ = prior_state(conn, season_id, "production", week, team_ids)
            ruling, _ = contest_ruling(conn, season_id, "production", week)
            subs = {int(k): int(v) for k, v in ruling["payload"].get("substitutions", {}).items()}
            if not subs.keys() <= set(qualifiers):
                raise Unresolved("substitution does not name an original qualifier")
            candidate = tuple(sorted(subs.get(t, t) for t in qualifiers))
            if len(candidate) != 2 or len(set(candidate)) != 2 or not set(candidate) <= alive:
                raise Unresolved("invalid gulag participants")
            pair = candidate
        except Unresolved:
            pass
        result.append((week, "archive_gulag_pair", {"team_ids": list(pair)}))
    return result
