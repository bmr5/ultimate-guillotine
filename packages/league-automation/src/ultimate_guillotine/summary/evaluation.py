"""Probability evaluation against final results, with one forecast per week/cohort."""

from collections import defaultdict
from statistics import mean


def outcomes(snapshot: dict, scores: dict[int, float]) -> dict[int, int] | None:
    live = [t["team_id"] for t in snapshot["teams"] if not t["is_eliminated"]]
    if not set(live) <= scores.keys():
        return None
    phase = snapshot["phase"]
    kind = phase["kind"]
    gulag = phase["gulag_team_ids"] if kind in ("gulag", "double") else []
    if kind in ("gulag", "double") and (len(gulag) != 2 or phase["gulag_source"] == "unknown"):
        return None
    pool = [i for i in live if i not in gulag]
    groups = [(pool, 2 if kind in ("entry", "gulag") else 1)]
    if gulag:
        groups.append((gulag, 1))
    result = dict.fromkeys(live, 0)
    for ids, count in groups:
        if len(ids) <= count:
            return None
        ordered = sorted(ids, key=lambda i: scores[i])
        # Do not invent an adjudication for a tied cutoff.
        if scores[ordered[count - 1]] == scores[ordered[count]]:
            return None
        for i in ordered[:count]:
            result[i] = 1
    return result


def evaluate(forecasts: list[dict], finals: dict, final_lineups: dict) -> dict:
    seen = set()
    observations = defaultdict(list)
    pending = ambiguous = legacy = 0
    for f in sorted(forecasts, key=lambda x: x["snapshot_at"]):
        if not f.get("inputs"):
            legacy += 1
            continue
        snap = f["inputs"]["snapshot"]
        horizon = (
            "pregame"
            if all(
                s["status"] in ("remaining", "out", "empty", "bye")
                for t in snap["teams"]
                for s in t["starters"]
            )
            else "in_game"
        )
        key = (f["season_id"], f["week"], f["model_version"], horizon)
        if key in seen:
            continue
        seen.add(key)
        scores = finals.get((f["season_id"], f["week"]))
        if scores is None:
            pending += 1
            continue
        actual = outcomes(snap, scores)
        if actual is None:
            ambiguous += 1
            continue
        frozen_teams = {t["team_id"]: t for t in snap["teams"]}
        for row in f["results"]:
            team_id = row["team_id"]
            lineup = final_lineups.get((f["season_id"], f["week"], team_id))
            frozen = {
                s["sleeper_player_id"]
                for s in frozen_teams[team_id]["starters"]
                if s["sleeper_player_id"]
            }
            changed = None if lineup is None else frozen != set(lineup) - {"0"}
            observations[(f["model_version"], horizon, row["adverse_event"])].append(
                {
                    "season": f["season_id"],
                    "week": f["week"],
                    "team_id": team_id,
                    "p": row["probability"],
                    "y": actual[team_id],
                    "lineup_changed": changed,
                    "point_error": row["projected_final"] - scores[team_id],
                }
            )
    cohorts = []
    for (model, horizon, event), rows in observations.items():
        bins = []
        for i in range(10):
            group = [r for r in rows if min(9, int(r["p"] * 10)) == i]
            if group:
                bins.append(
                    {
                        "range": [i / 10, (i + 1) / 10],
                        "count": len(group),
                        "forecast": mean(r["p"] for r in group),
                        "observed": mean(r["y"] for r in group),
                    }
                )
        unchanged = [r for r in rows if r["lineup_changed"] is False]
        cohorts.append(
            {
                "model": model,
                "horizon": horizon,
                "event": event,
                "weeks": len({(r["season"], r["week"]) for r in rows}),
                "teams": len(rows),
                "brier": mean((r["p"] - r["y"]) ** 2 for r in rows),
                "point_mae": mean(abs(r["point_error"]) for r in rows),
                "lineups_changed": sum(r["lineup_changed"] is True for r in rows),
                "lineups_unknown": sum(r["lineup_changed"] is None for r in rows),
                "unchanged_brier": mean((r["p"] - r["y"]) ** 2 for r in unchanged)
                if unchanged
                else None,
                "calibration": bins,
            }
        )
    return {
        "cohorts": cohorts,
        "pending_weeks": pending,
        "ambiguous_weeks": ambiguous,
        "legacy_forecasts_without_inputs": legacy,
        "method": "Earliest forecast per season/week/model/horizon; final results only. Pregame and in-game kept separate. Team outcomes within a week are dependent; counts are not independent trials.",
    }


def load_evaluation(conn) -> dict:
    rows = conn.execute("""select distinct on (season_id, week, model_version, inputs->>'horizon')
        season_id, week, model_version, snapshot_at, results, inputs
        from public.survival_snapshots where inputs is not null
        order by season_id, week, model_version, inputs->>'horizon', snapshot_at, id""").fetchall()
    forecasts = [
        dict(zip(("season_id", "week", "model_version", "snapshot_at", "results", "inputs"), r))
        for r in rows
    ]
    scores = conn.execute("""select season_id,week,team_id,points,is_final from
        (select distinct on (season_id,week,team_id) season_id,week,team_id,points,is_final
         from public.weekly_results order by season_id,week,team_id,state_version desc) latest""").fetchall()
    finals = defaultdict(dict)
    for season, week, team, points, final in scores:
        if final:
            finals[(season, week)][team] = float(points)
    lineups = {
        (s, w, t): ids
        for s, w, t, ids in conn.execute(
            "select season_id,week,team_id,starters from public.team_week_scores"
        ).fetchall()
    }
    result = evaluate(forecasts, finals, lineups)
    result["legacy_forecasts_without_inputs"] = conn.execute(
        "select count(*) from public.survival_snapshots where inputs is null"
    ).fetchone()[0]
    return result
