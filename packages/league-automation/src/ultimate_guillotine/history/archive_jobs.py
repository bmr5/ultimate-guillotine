"""Prospective capture, durable week-close retries, and score-stable adjudication."""

from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from psycopg.types.json import Jsonb

from ultimate_guillotine.history.adjudicator import RULES_VERSION, Unresolved, adjudicate
from ultimate_guillotine.history.archive_store import (
    contest_ruling,
    digest,
    invalidate_later,
    prior_state,
    publish,
    rows,
    update_current_state,
)
from ultimate_guillotine.sleeper.roster_state import classify_holdings
from ultimate_guillotine.summary.schedule import parse_schedule

CENTRAL = ZoneInfo("America/Chicago")
STABILITY = timedelta(minutes=30)
RETRY = timedelta(minutes=15)
CORRECTION_WINDOW = timedelta(days=7)


def retry_at(now: datetime) -> datetime:
    return now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0) + RETRY


def numeric(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def safe_schedule(client, season: int) -> list:
    try:
        return client.get_schedule(season)
    except (httpx.HTTPError, ValueError):
        return []  # capture still saves available roster/money evidence


def validated_schedule(payload: list, week: int, baseline: list | None = None):
    raw = [g for g in payload if isinstance(g, dict) and g.get("week") == week]
    parsed = parse_schedule(raw)
    if not raw or len(parsed) != len(raw) or any(g.date is None for g in parsed):
        raise Unresolved("schedule is missing or malformed")
    ids = [g.game_id for g in parsed]
    if len(set(ids)) != len(ids):
        raise Unresolved("duplicate games in schedule")
    if baseline is not None:
        original = {g["game_id"] for g in baseline if g.get("week") == week}
        if set(ids) != original:
            raise Unresolved("schedule game IDs changed; refresh the season schedule after review")
    return parsed


def checkpoint_at(games) -> datetime:
    # NFL scoring week: Monday following the first scheduled game, even in a week
    # with no Monday game. Reschedules are gated by actual status, not this clock.
    first = min(g.date for g in games)
    monday = first + timedelta(days=(0 - first.weekday()) % 7)
    return datetime.combine(monday, time(23, 30), CENTRAL).astimezone(UTC)


def verification_at(games) -> datetime:
    checkpoint = checkpoint_at(games).astimezone(CENTRAL)
    return datetime.combine(checkpoint.date() + timedelta(days=1), time(8), CENTRAL).astimezone(UTC)


def enable(conn, client, league_id: str, season: int, scope: str, now: datetime):
    league = client.get_league(league_id)
    if season != 2026 or league.season_year != season or league.total_rosters != 18:
        raise ValueError("only the reviewed 18-team 2026 rules can be enabled")
    season_rows = rows(
        conn,
        "select id, sleeper_league_id, expected_rosters from public.seasons where year=%s",
        (season,),
    )
    if (
        not season_rows
        or season_rows[0]["sleeper_league_id"] != league_id
        or season_rows[0]["expected_rosters"] != 18
    ):
        raise ValueError("season/league identity mismatch; run Sleeper sync first")
    season_id = season_rows[0]["id"]
    schedule = client.get_schedule(season)
    if len(schedule) < 250:
        raise ValueError("incomplete season schedule")
    weeks = {week: validated_schedule(schedule, week) for week in range(1, 18)}
    with conn.transaction():
        conn.execute("select pg_advisory_xact_lock(82426, %s)", (season_id,))
        previous = rows(
            conn, "select * from private.archive_seasons where season_id=%s", (season_id,)
        )
        if previous and previous[0]["scope"] != scope:
            raise ValueError("cannot change the scope of an existing archive")
        conn.execute(
            """insert into private.archive_seasons
            (season_id,enabled,scope,rules_version,started_at,schedule)
            values (%s,true,%s,%s,%s,%s) on conflict (season_id) do update set enabled=true""",
            (season_id, scope, RULES_VERSION, now, Jsonb(schedule)),
        )
        for week, games in weeks.items():
            conn.execute(
                """insert into private.archive_week_jobs(season_id,scope,week,next_check_at)
                values (%s,%s,%s,%s) on conflict do nothing""",
                (season_id, scope, week, max(now, checkpoint_at(games))),
            )
    return season_id


def configuration(conn) -> dict | None:
    configs = rows(
        conn,
        """select a.*, s.year as season, s.sleeper_league_id
        from private.archive_seasons a join public.seasons s on s.id=a.season_id
        where a.enabled order by s.year desc""",
    )
    if not configs:
        return None
    if len(configs) != 1 or configs[0]["season"] != 2026:
        raise ValueError("one reviewed 2026 archive must be active")
    return configs[0]


def capture(conn, client, config: dict, week: int, now: datetime, *, schedule=None) -> dict:
    """Retain every team's as-observed roster and raw money. No inferred balances."""
    season_id, scope = config["season_id"], config["scope"]
    league_id = config["sleeper_league_id"]
    league = client.get_league(league_id)
    if (
        league.season_year != config["season"]
        or league.league_id != league_id
        or league.total_rosters != 18
    ):
        raise Unresolved("Sleeper league no longer matches the configured 2026 season")
    rosters = client.get_rosters(league_id)
    users = {u.user_id: u for u in client.get_users(league_id)}
    matchups = client.get_matchups(league_id, week)
    schedule = safe_schedule(client, config["season"]) if schedule is None else schedule
    try:
        week_games = validated_schedule(schedule, week, config["schedule"])
    except Unresolved:
        week_games = []
    mapping = rows(
        conn,
        """select t.id,t.sleeper_roster_id,t.sleeper_user_id,t.team_name,
        m.nickname,m.sleeper_display_name from public.teams t join public.members m on m.id=t.member_id
        where t.season_id=%s""",
        (season_id,),
    )
    by_roster = {t["sleeper_roster_id"]: t for t in mapping}
    if len(by_roster) != 18 or len(rosters) != 18 or len({r.roster_id for r in rosters}) != 18:
        raise Unresolved("capture requires all 18 distinct team identities")
    ids = {p for roster in rosters for p in (*roster.players, *roster.starters) if p != "0"}
    ids.update(
        str(p)
        for m in matchups
        if isinstance(m, dict)
        for p in (m.get("starters") or [])
        if p != "0"
    )
    directory = {
        p["sleeper_player_id"]: p
        for p in rows(
            conn,
            "select sleeper_player_id,full_name,position from public.players where sleeper_player_id=any(%s)",
            (list(ids),),
        )
    }
    teams = {}
    for roster in rosters:
        team = by_roster.get(roster.roster_id)
        user = users.get(roster.owner_id)
        if team is None or user is None or team["sleeper_user_id"] != roster.owner_id:
            raise Unresolved("roster owner mapping changed; sync and review identities")
        budget = numeric(league.settings.get("waiver_budget"))
        used = numeric(roster.settings.get("waiver_budget_used"))
        amount = budget - used if budget is not None and used is not None else None
        holdings = classify_holdings(roster, league.roster_positions).holdings
        teams[str(team["id"])] = {
            "roster_id": roster.roster_id,
            "team_label": user.team_name[:120],
            "manager_label": (team["nickname"] or user.display_name)[:120],
            "starters": roster.starters,
            "faab_remaining": float(amount) if amount is not None else None,
            "players": [
                {
                    "player_id": h.sleeper_player_id,
                    "player_label": directory.get(h.sleeper_player_id, {}).get("full_name")
                    or h.sleeper_player_id,
                    "position": directory.get(h.sleeper_player_id, {}).get("position"),
                    "slot": h.slot,
                    "owned": h.sleeper_player_id
                    in set(roster.players + roster.reserve + roster.taxi),
                }
                for h in holdings
            ],
            "roster_fields_present": sorted(roster.model_fields_set),
            "raw_roster": roster.model_dump(mode="json"),
        }
    payload = {
        "teams": teams,
        "matchups": matchups,
        "directory": directory,
        "league": league.model_dump(mode="json"),
        "schedule": [g for g in schedule if isinstance(g, dict) and g.get("week") == week],
    }
    key = digest(payload)
    with conn.transaction():
        conn.execute("select pg_advisory_xact_lock(82426, %s)", (season_id,))
        last = rows(
            conn,
            """select * from private.team_state_observations
            where season_id=%s and scope=%s and week=%s order by observed_at desc,id desc limit 1""",
            (season_id, scope, week),
        )
        if last and last[0]["content_hash"] == key and now - last[0]["observed_at"] < RETRY:
            result = last[0]
        else:
            observation_id = conn.execute(
                """insert into private.team_state_observations
                (season_id,scope,week,observed_at,content_hash,payload) values (%s,%s,%s,%s,%s,%s)
                returning id""",
                (season_id, scope, week, now, key, Jsonb(payload)),
            ).fetchone()[0]
            result = {"id": observation_id, "observed_at": now, "payload": payload}
        conn.execute(
            "update private.archive_seasons set last_capture_at=%s where season_id=%s",
            (now, season_id),
        )
        if week_games and all(g.status in ("complete", "canceled") for g in week_games):
            cutoff = result
            if last and now - last[0]["observed_at"] <= timedelta(minutes=20):
                prior = last[0]
                # A reset between the last live-game poll and the completion poll must
                # not become the final roster. Keep the preceding observation.
                if prior["payload"]["teams"] != teams:
                    cutoff = prior
            conn.execute(
                """update private.archive_week_jobs set cutoff_observation_id=coalesce(cutoff_observation_id,%s),
                first_complete_at=coalesce(first_complete_at,%s)
                where season_id=%s and scope=%s and week=%s""",
                (cutoff["id"], now, season_id, scope, week),
            )
    return result


def capture_current(conn, client, now: datetime) -> int:
    config = configuration(conn)
    if config is None:
        return 0
    state = client.get_nfl_state()
    if str(state.get("season")) != str(config["season"]) or state.get("season_type") != "regular":
        return 0
    week = state.get("week")
    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 17:
        return 0
    schedule = safe_schedule(client, config["season"])
    # The stored jobs keep an unfinished week pinned even if Sleeper advances its current week.
    pending = rows(
        conn,
        """select week from private.archive_week_jobs where season_id=%s and scope=%s
        and first_complete_at is null and week < %s and next_check_at <= %s""",
        (config["season_id"], config["scope"], week, now),
    )
    for number in sorted({week, *(j["week"] for j in pending)}):
        capture(conn, client, config, number, now, schedule=schedule)
    return 1 + len(pending)


def score_inputs(payload: dict) -> tuple[dict[int, Decimal], dict[int, dict]]:
    team_by_roster = {t["roster_id"]: int(k) for k, t in payload["teams"].items()}
    scores, matchups = {}, {}
    for record in payload["matchups"]:
        if not isinstance(record, dict) or isinstance(record.get("roster_id"), bool):
            raise Unresolved("malformed matchup record")
        team_id = team_by_roster.get(record.get("roster_id"))
        if team_id is None or team_id in matchups:
            raise Unresolved("unknown or duplicate matchup roster")
        override = record.get("custom_points")
        score = numeric(override if override is not None else record.get("points"))
        if score is None:
            raise Unresolved("missing or invalid official score")
        if not isinstance(record.get("starters"), list):
            raise Unresolved("missing scoring lineup")
        scores[team_id] = score
        matchups[team_id] = record
    return scores, matchups


def evidence_for_job(conn, job: dict, config: dict) -> dict:
    saved = rows(
        conn,
        "select * from private.team_state_observations where id=%s",
        (job["cutoff_observation_id"],),
    )
    if not saved:
        raise Unresolved("no saved week-close observation")
    evidence = saved[0]
    # Exact whistle times are not in this schedule feed. Report an observed cutoff.
    # A nearby pre-close capture establishes coverage, without using Tuesday balances.
    before = rows(
        conn,
        """select observed_at from private.team_state_observations
        where season_id=%s and scope=%s and week=%s and observed_at < %s
        order by observed_at desc limit 1""",
        (config["season_id"], config["scope"], job["week"], evidence["observed_at"]),
    )
    evidence["coverage"] = (
        "complete"
        if before and evidence["observed_at"] - before[0]["observed_at"] <= timedelta(minutes=20)
        else "partial"
    )
    return evidence


def adjudicate_job(conn, config: dict, job: dict, fresh: dict, now: datetime) -> str:
    season_id, scope, week = config["season_id"], config["scope"], job["week"]
    try:
        games = validated_schedule(fresh["payload"]["schedule"], week, config["schedule"])
        if not all(g.status in ("complete", "canceled") for g in games):
            if job["status"] == "confirmed":
                conn.execute(
                    """update private.archive_week_jobs set cutoff_observation_id=null,
                    first_complete_at=null where season_id=%s and scope=%s and week=%s""",
                    (season_id, scope, week),
                )
                raise Unresolved("Previously finished game reopened; waiting for completion")
            conn.execute(
                """update private.archive_week_jobs set next_check_at=%s,
                candidate_hash=null,stable_since=null,last_error='Games are not complete'
                where season_id=%s and scope=%s and week=%s""",
                (retry_at(now), season_id, scope, week),
            )
            return "pending"
        evidence = evidence_for_job(conn, job, config)
        scores, matchups = score_inputs(fresh["payload"])
        team_ids = {int(k) for k in evidence["payload"]["teams"]}
        alive, qualifiers, dependencies = prior_state(conn, season_id, scope, week, team_ids)
        ruling, contracts = contest_ruling(conn, season_id, scope, week)
        rule = ruling["payload"]
        substitutions = {int(k): int(v) for k, v in rule.get("substitutions", {}).items()}
        # Values and identities in a ruling are checked again by the pure adjudicator.
        outcome = adjudicate(
            week, alive, qualifiers, scores, substitutions, tuple(rule.get("tie_order", []))
        )
        key = digest(
            {
                "scores": scores,
                "lineups": matchups,
                "outcome": asdict(outcome),
                "ruling": ruling,
                "contracts": [(t["id"], t["revision_id"]) for t in contracts],
                "dependencies": dependencies,
                "cutoff": evidence["id"],
                "rules": RULES_VERSION,
            }
        )
        stable_since = job["stable_since"] if job["candidate_hash"] == key else now
        if job["published_hash"] == key and job["status"] == "confirmed":
            status = "confirmed"
        elif now < verification_at(games) or now - stable_since < STABILITY:
            conn.execute(
                """update private.archive_week_jobs set candidate_hash=%s, stable_since=%s,
                next_check_at=%s,last_error=null where season_id=%s and scope=%s and week=%s""",
                (key, stable_since, retry_at(now), season_id, scope, week),
            )
            # Retain the last official ruling during score stabilization of a correction.
            if job["status"] != "confirmed":
                publish(
                    conn,
                    season_id=season_id,
                    season=config["season"],
                    scope=scope,
                    week=week,
                    status="provisional",
                    input_hash=key,
                    now=now,
                    outcome=outcome,
                    evidence=evidence,
                    scores=scores,
                    matchup_by_team=matchups,
                )
            return "pending"
        else:
            entries = {}
            if 2 <= week <= 12:
                prior_job = rows(
                    conn,
                    """select * from private.archive_week_jobs
                    where season_id=%s and scope=%s and week=%s""",
                    (season_id, scope, week - 1),
                )[0]
                entry_saved = evidence_for_job(conn, prior_job, config)
                entry_saved["coverage"] = "partial"  # pre-reset boundary was observed, not exact
                for event in outcome.events:
                    if event.kind == "gulag_entered":
                        entries[event.team] = entry_saved
            publish(
                conn,
                season_id=season_id,
                season=config["season"],
                scope=scope,
                week=week,
                status="confirmed",
                input_hash=key,
                now=now,
                outcome=outcome,
                evidence=evidence,
                scores=scores,
                matchup_by_team=matchups,
                entry_evidence=entries,
            )
            invalidate_later(conn, season_id, config["season"], scope, week, now)
            update_current_state(conn, season_id, scope)
            status = "confirmed"
        interval = (
            timedelta(hours=1)
            if now < job["first_complete_at"] + CORRECTION_WINDOW
            else timedelta(days=1)
        )
        # Keep a daily correction read through season end. Never refetch current rosters as
        # replacement evidence: cutoff_observation_id remains pinned on every revision.
        conn.execute(
            """update private.archive_week_jobs set status=%s,candidate_hash=%s,
            stable_since=%s,published_hash=%s,next_check_at=%s,last_error=null
            where season_id=%s and scope=%s and week=%s""",
            (status, key, stable_since, key, now + interval, season_id, scope, week),
        )
        return status
    except Unresolved as exc:
        reason = str(exc)
        publish(
            conn,
            season_id=season_id,
            season=config["season"],
            scope=scope,
            week=week,
            status="unresolved",
            input_hash=digest(("unresolved", reason)),
            now=now,
            outcome=None,
            evidence=None,
            scores={},
            matchup_by_team={},
        )
        invalidate_later(conn, season_id, config["season"], scope, week, now)
        update_current_state(conn, season_id, scope)
        conn.execute(
            """update private.archive_week_jobs set status='unresolved',last_error=%s,
            candidate_hash=null,stable_since=null,next_check_at=%s
            where season_id=%s and scope=%s and week=%s""",
            (reason, retry_at(now), season_id, scope, week),
        )
        return "unresolved"


def tick(conn, client, now: datetime) -> dict[str, int]:
    config = configuration(conn)
    counts = {"pending": 0, "confirmed": 0, "unresolved": 0}
    if config is None:
        return counts
    last_game_date = max(
        date.fromisoformat(g["date"]) for g in config["schedule"] if g["week"] == 17
    )
    if now.astimezone(CENTRAL).date() > last_game_date + timedelta(days=14):
        return counts
    # A season lock serializes publication, capture, and operator rulings. The scheduler's
    # process can restart at any point; all due times, hashes, and cutoff IDs are persisted.
    with conn.transaction():
        locked = conn.execute(
            "select pg_try_advisory_xact_lock(82426,%s)", (config["season_id"],)
        ).fetchone()[0]
        if not locked:
            return counts
        jobs = rows(
            conn,
            """select * from private.archive_week_jobs
            where season_id=%s and scope=%s and next_check_at <= %s order by week""",
            (config["season_id"], config["scope"], now),
        )
        schedule = safe_schedule(client, config["season"]) if jobs else []
        for job in jobs:
            fresh = capture(conn, client, config, job["week"], now, schedule=schedule)
            # Capture may have just established the first final observation.
            job = rows(
                conn,
                """select * from private.archive_week_jobs
                where season_id=%s and scope=%s and week=%s""",
                (config["season_id"], config["scope"], job["week"]),
            )[0]
            verdict = adjudicate_job(conn, config, job, fresh, now)
            counts[verdict] += 1
    return counts
