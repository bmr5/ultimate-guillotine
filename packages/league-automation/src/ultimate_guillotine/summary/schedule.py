"""Sleeper's public NFL schedule: which games are over, which are still to come.

``https://api.sleeper.app/schedule/nfl/regular/{season}`` answers with one object per
game -- ``week``, ``date``, ``home``, ``away``, ``status``, ``game_id`` -- and it is
the one source of "has this starter played yet" the odds depend on. Verified
2026-09-10 against the 2026 slate: 273 games, statuses ``pre_game``, ``complete``
and ``canceled``.

A game's status is read into one of three words. ``complete`` and ``canceled`` are
``done``; ``pre_game`` is ``remaining``; **anything else is ``live``**, including a
status this build has never seen. That is the conservative reading -- a game in a
state we cannot name may still be scoring, so its starters keep their variance
rather than being called finished on a word nobody read.
"""

import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from ultimate_guillotine.summary.models import DayState

GameState = Literal["done", "remaining", "live"]

DONE_STATUSES: frozenset[str] = frozenset({"complete", "canceled"})
PRE_STATUSES: frozenset[str] = frozenset({"pre_game"})


@dataclass(frozen=True)
class Game:
    game_id: str
    week: int
    date: date | None
    home: str
    away: str
    status: str
    remaining_fraction: Decimal | None = None


def _date_or_none(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_schedule(payload: object) -> list[Game]:
    """Every well-formed game in the payload, in payload order. The rest are dropped."""
    if not isinstance(payload, list):
        return []
    games: list[Game] = []
    for record in payload:
        if not isinstance(record, dict):
            continue
        week = record.get("week")
        home, away, status = record.get("home"), record.get("away"), record.get("status")
        game_id = record.get("game_id")
        if isinstance(week, bool) or not isinstance(week, int):
            continue
        if not all(isinstance(v, str) and v for v in (home, away, status, game_id)):
            continue
        games.append(
            Game(
                game_id=str(game_id),
                week=week,
                date=_date_or_none(record.get("date")),
                home=str(home),
                away=str(away),
                status=str(status),
            )
        )
    return games


def games_for_week(games: Iterable[Game], week: int) -> dict[str, Game]:
    """The week's games keyed by NFL team, both sides of each game."""
    by_team: dict[str, Game] = {}
    for game in games:
        if game.week != week:
            continue
        by_team[game.home] = game
        by_team[game.away] = game
    return by_team


def game_state(game: Game) -> GameState:
    if game.status in DONE_STATUSES:
        return "done"
    if game.status in PRE_STATUSES:
        return "remaining"
    return "live"


def _distinct(week_games: Mapping[str, Game]) -> list[Game]:
    seen: dict[str, Game] = {}
    for game in week_games.values():
        seen.setdefault(game.game_id, game)
    return list(seen.values())


def day_state(week_games: Mapping[str, Game]) -> DayState:
    """What the week looks like from the schedule alone."""
    games = _distinct(week_games)
    if not games:
        return "unknown"
    states = {game_state(g) for g in games}
    if states == {"remaining"}:
        return "outlook"
    if states == {"done"}:
        return "final"
    return "midweek"


def games_final(week_games: Mapping[str, Game]) -> tuple[int, int]:
    """``(games done, games this week)``, over distinct games."""
    games = _distinct(week_games)
    return sum(1 for g in games if game_state(g) == "done"), len(games)


def fetch_week_games(client: Any, season: int, week: int) -> dict[str, Game] | None:
    """The week's games by team, or ``None`` when the feed could not be read.

    ``None`` rather than an empty mapping, on purpose: no schedule is not the same
    as a week with no games, and the caller withholds the odds on the first and
    posts an outlook on the second.
    """
    try:
        payload = client.get_schedule(season)
    except Exception:  # noqa: BLE001 - any failure to read the feed is the same answer
        return None
    games = games_for_week(parse_schedule(payload), week)
    if not hasattr(client, "get_game_clocks"):
        return games or None
    try:
        clocks = parse_clocks(client.get_game_clocks(season, week), season, week)
        if not games.keys() <= clocks.keys():
            raise ValueError("Incomplete game clock slate")
        games.update(clocks)
    except Exception as exc:  # noqa: BLE001 - any unavailable clock withholds live odds
        logging.getLogger(__name__).warning("Game clocks unavailable: %s", type(exc).__name__)
        return None
    return games or None


def parse_clocks(payload: object, season: int, week: int) -> dict[str, Game]:
    """Validate the requested ESPN regular-season slate and retain game-clock fractions."""
    if (
        not isinstance(payload, dict)
        or payload.get("season", {}).get("year") != season
        or payload.get("season", {}).get("type") != 2
        or payload.get("week", {}).get("number") != week
    ):
        raise ValueError("Wrong clock scope")
    games = {}
    aliases = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}
    for event in payload.get("events", []):
        if (
            event.get("season", {}).get("year") != season
            or event.get("season", {}).get("type") != 2
            or event.get("week", {}).get("number") != week
        ):
            continue
        state = event.get("status", {})
        kind = state.get("type", {})
        if kind.get("state") == "post" and kind.get("completed") is True:
            status, fraction = "complete", Decimal(0)
        elif kind.get("state") == "pre":
            status, fraction = "pre_game", Decimal(1)
        elif kind.get("state") == "in":
            period, clock = state.get("period"), state.get("clock")
            if (
                not isinstance(period, int)
                or isinstance(period, bool)
                or period < 1
                or not isinstance(clock, (int, float))
                or not math.isfinite(clock)
                or not 0 <= clock <= 900
            ):
                continue
            seconds = (4 - period) * 900 + clock if period <= 4 else min(clock, 600)
            status, fraction = "in_game", Decimal(str(seconds)) / Decimal(3600)
        else:
            continue
        competitors = event["competitions"][0]["competitors"]
        if len(competitors) != 2:
            continue
        codes = [
            aliases.get(c["team"]["abbreviation"], c["team"]["abbreviation"]) for c in competitors
        ]
        game = Game(str(event["id"]), week, None, codes[0], codes[1], status, fraction)
        for code in codes:
            games[code] = game
    if not games:
        raise ValueError("Missing clocks")
    return games
