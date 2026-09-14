"""Retrospective Sleeper fit/check. Historical projections may have been revised."""

import hashlib
import json
import math
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean

import httpx

from ultimate_guillotine.sleeper.scoring import score_stat_line, scoring_version
from ultimate_guillotine.summary.distributions import draw_points

THRESHOLDS = {"QB": 5, "RB": 3, "WR": 3, "TE": 3, "K": 1, "DEF": 1}


def historical_week(year: int, week: int, scoring: dict, cache: Path) -> list[dict]:
    path = cache / f"{year}-{week}-{scoring_version(scoring)}.json"
    if path.exists():
        return json.loads(path.read_text())
    with httpx.Client(timeout=60) as http:
        payloads = []
        for endpoint in ("projections", "stats"):
            response = http.get(
                f"https://api.sleeper.app/{endpoint}/nfl/{year}/{week}",
                params={"season_type": "regular"},
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or not rows:
                raise ValueError("Historical feed missing")
            payloads.append(
                [
                    r
                    for r in rows
                    if str(r.get("season")) == str(year)
                    and r.get("week") == week
                    and r.get("season_type") == "regular"
                ]
            )
    actuals = {r["player_id"]: r for r in payloads[1]}
    result = []
    for p in payloads[0]:
        position = (p.get("player") or {}).get("position")
        if position not in THRESHOLDS:
            continue
        projected = score_stat_line(p.get("stats") or {}, scoring)
        if projected is None or projected < THRESHOLDS[position]:
            continue
        actual = actuals.get(p["player_id"])
        # Missing stats are not proof of a zero; exclude unavailable outcomes.
        if actual is None:
            continue
        points = score_stat_line(actual.get("stats") or {}, scoring)
        if points is None:
            if not (actual.get("stats") or {}).get("gms_active"):
                continue
            points = 0
        result.append(
            {
                "year": year,
                "week": week,
                "id": p["player_id"],
                "position": position,
                "projection": float(projected),
                "actual": float(points),
                "projection_updated_at": p.get("updated_at"),
            }
        )
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return result


def fit(rows: list[dict]) -> dict:
    positions = {}
    for position in THRESHOLDS:
        sample = [r for r in rows if r["position"] == position]
        if len(sample) < 100:
            raise ValueError(f"Insufficient history for {position}: {len(sample)}")
        ratios = [r["actual"] / r["projection"] for r in sample]
        # Keep the projection as the mean; estimate dispersion about that forecast,
        # including forecast bias, rather than fitting to this week's surprises.
        cv = math.sqrt(mean((r - 1) ** 2 for r in ratios))
        positions[position] = {
            "cv": cv,
            "zero_probability": mean(r["actual"] <= 0 for r in sample),
            "sigma_floor": 2.0,
            "def_sigma": math.sqrt(mean((r["actual"] - r["projection"]) ** 2 for r in sample)),
            "samples": len(sample),
            "mean_actual_to_projection": mean(ratios),
        }
    return positions


def check(rows: list[dict], positions: dict) -> dict:
    rng = random.Random(2025)
    results = {}
    legacy = {"QB": 0.35, "RB": 0.5, "WR": 0.55, "TE": 0.6, "K": 0.55, "DEF": 0.6}
    for position in THRESHOLDS:
        sample = [r for r in rows if r["position"] == position]
        covered = old_covered = 0
        widths = []
        crps = old_crps = 0.0
        for row in sample:
            mu = row["projection"]
            actual = row["actual"]
            config = positions[position]
            sigma = config["def_sigma"] if position == "DEF" else max(2, mu * config["cv"])
            draws = sorted(
                draw_points(rng, mu, sigma * sigma, position, config["zero_probability"])
                for _ in range(256)
            )
            old = sorted(max(0, rng.gauss(mu, max(2, mu * legacy[position]))) for _ in range(256))
            covered += draws[25] <= actual <= draws[230]
            old_covered += old[25] <= actual <= old[230]
            widths.append(draws[230] - draws[25])

            # Empirical CRPS penalizes excessive interval width as well as misses.
            def score(values, actual=actual):
                n = len(values)
                return mean(abs(v - actual) for v in values) - sum(
                    (2 * i - n + 1) * v for i, v in enumerate(values)
                ) / (n * n)

            crps += score(draws)
            old_crps += score(old)
        results[position] = {
            "samples": len(sample),
            "coverage_80": covered / len(sample),
            "legacy_coverage_80": old_covered / len(sample),
            "mean_interval_width": mean(widths),
            "crps": crps / len(sample),
            "legacy_crps": old_crps / len(sample),
        }
    return results


def train(scoring: dict, cache: Path, output: Path) -> dict:
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(
            pool.map(
                lambda scope: historical_week(*scope, scoring, cache),
                [(year, week) for year in (2024, 2025) for week in range(1, 18)],
            )
        )
    rows = [row for batch in batches for row in batch]
    positions = fit([r for r in rows if r["year"] == 2024])
    report = {
        "version": "sleeper-2024-gamma-v1",
        "train_season": 2024,
        "check_season": 2025,
        "source": "Sleeper historical projections and stats, regular weeks 1-17",
        "limitations": "Retrospective: historical projections may be revised after kickoff. Missing actual rows excluded. Live clock scaling is not validated by full-game history.",
        "scoring_settings": scoring,
        "scoring_version": scoring_version(scoring),
        "data_hash": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        "positions": positions,
        "holdout": check([r for r in rows if r["year"] == 2025], positions),
    }
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report
