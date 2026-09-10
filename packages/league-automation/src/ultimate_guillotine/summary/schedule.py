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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
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
    return games_for_week(parse_schedule(payload), week)
