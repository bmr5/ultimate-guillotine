"""Read historical competitive scores without counting cleared or retired-player rosters."""

from decimal import ROUND_HALF_UP, Decimal


def saved_matchup_roster(matchup: dict, positions: list[str], directory: dict) -> dict:
    """Keep only the historical matchup's lineup, bench, and public player fields."""
    slots = [slot for slot in positions if slot not in {"BN", "IR", "TAXI"}]
    starters = matchup["starters"]
    if len(starters) > len(slots):
        raise ValueError("Matchup has more starters than the league's starting slots")
    per_player = matchup.get("players_points") or {}
    per_slot = matchup.get("starters_points") or []

    def player(player_id, slot, raw_points):
        player_id = str(player_id) if player_id and str(player_id) != "0" else None
        info = directory.get(player_id, {})
        points = None
        if isinstance(raw_points, (float, int)) and not isinstance(raw_points, bool):
            value = Decimal(str(raw_points))
            if value.is_finite():
                points = float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        return {
            "player_id": player_id,
            "player_label": (info.get("full_name") or f"Player {player_id}")
            if player_id
            else "Empty slot",
            "position": info.get("position") if player_id else None,
            "slot": slot,
            "points": points if player_id else 0,
        }

    lineup = []
    for index, slot in enumerate(slots):
        player_id = starters[index] if index < len(starters) else None
        raw = per_slot[index] if index < len(per_slot) else per_player.get(str(player_id))
        lineup.append(player(player_id, slot, raw))
    started = {p["player_id"] for p in lineup}
    bench = [
        player(p, "Bench", per_player.get(str(p)))
        for p in dict.fromkeys(matchup.get("players") or [])
        if p and str(p) != "0" and str(p) not in started
    ]
    return {"starters": lineup, "bench": bench}


def competitive_scores(
    weeks: dict[int, list[dict]], *, required_starters: int | None = None
) -> tuple[list[dict], dict[int, int]]:
    """A cleared roster stays out, even if it receives a keeper in a later week.

    Archived leagues retain blank slots and sometimes retired-player placeholders
    after a cut. A one-player roster is a retained keeper, not a competitive lineup.
    An incomplete all-zero lineup is also excluded. Full-lineup zero scores and
    commissioner overrides remain valid. Missing/malformed inputs refuse import.
    """
    retired: set[int] = set()
    excluded_from: dict[int, int] = {}
    result = []
    for week, matchups in sorted(weeks.items()):
        if not matchups:
            raise ValueError(f"Missing matchups for week {week}")
        seen = set()
        for row in matchups:
            roster = row["roster_id"]
            if roster in seen:
                raise ValueError(f"Duplicate roster in week {week}")
            seen.add(roster)
            starters = row.get("starters")
            if not isinstance(starters, list):
                raise TypeError(f"Missing lineup in week {week}")
            raw = row.get("custom_points")
            if raw is None:
                raw = row.get("points")
            if isinstance(raw, bool) or not isinstance(raw, (float, int)):
                raise TypeError(f"Invalid score in week {week}")
            points = Decimal(str(raw))
            if not points.is_finite():
                raise ValueError(f"Invalid score in week {week}")
            occupied = [str(p) for p in starters if p and str(p) != "0"]
            player_points = row.get("players_points") or {}
            placeholder = (
                row.get("custom_points") is None
                and points == 0
                and len(occupied) < len(starters)
                and all(player_points.get(p, 0) == 0 for p in occupied)
            )
            if len(occupied) <= 1 or placeholder:
                retired.add(roster)
                excluded_from.setdefault(roster, week)
            if roster in retired:
                continue
            result.append(
                {
                    "week": week,
                    "sleeper_roster_id": roster,
                    "points": points.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    "filled_starting_slots": len(set(occupied)),
                    "required_starters": required_starters,
                }
            )
    return result, excluded_from
