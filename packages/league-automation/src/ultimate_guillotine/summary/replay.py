"""Lossless JSON forecast inputs, independent of mutable league rows."""

import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal

from ultimate_guillotine.summary.models import EodSnapshot, Move, Phase, StarterLine, TeamLine


def encode(snapshot, result) -> dict:
    return json.loads(
        json.dumps(
            {
                "schema_version": 1,
                "model_version": result.model_version,
                "simulations": result.simulations,
                "seed": str(result.seed),
                "horizon": "pregame"
                if all(
                    s.status in ("remaining", "out", "empty", "bye")
                    for t in snapshot.live_teams()
                    for s in t.starters
                )
                else "in_game",
                "parameters": result.model_parameters,
                "snapshot": asdict(snapshot),
            },
            default=str,
        )
    )


def decode(payload: dict) -> EodSnapshot:
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported input schema")
    raw = dict(payload["snapshot"])
    teams = []
    for value in raw["teams"]:
        t = dict(value)
        starters = []
        for value in t["starters"]:
            s = dict(value)
            for k in ("projected", "points", "remaining_fraction"):
                s[k] = Decimal(s[k]) if s.get(k) is not None else None
            starters.append(StarterLine(**s))
        t["starters"] = tuple(starters)
        t["points"] = Decimal(t["points"])
        t["scores_synced_at"] = (
            datetime.fromisoformat(t["scores_synced_at"]) if t["scores_synced_at"] else None
        )
        teams.append(TeamLine(**t))
    raw["teams"] = tuple(teams)
    raw["phase"] = Phase(
        **{**raw["phase"], "gulag_team_ids": tuple(raw["phase"]["gulag_team_ids"])}
    )
    raw["moves"] = tuple(
        Move(
            **{
                **m,
                "occurred_at": datetime.fromisoformat(m["occurred_at"]),
                "adds": tuple(m["adds"]),
                "drops": tuple(m["drops"]),
            }
        )
        for m in raw["moves"]
    )
    for k in ("data_synced_at", "scores_synced_at", "moves_since"):
        raw[k] = datetime.fromisoformat(raw[k]) if raw[k] else None
    return EodSnapshot(**raw)


def replay(payload: dict):
    from ultimate_guillotine.summary.survival import MODEL_VERSION, simulate

    if payload["model_version"] != MODEL_VERSION:
        raise ValueError("Replay requires the saved model code version")
    return simulate(
        decode(payload),
        simulations=payload["simulations"],
        seed=int(payload["seed"]),
        model=payload["parameters"],
    )
