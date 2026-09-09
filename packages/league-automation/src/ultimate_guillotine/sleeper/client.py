"""Read-only client for the public Sleeper fantasy football API.

``SleeperClient`` exposes only read operations against
``https://api.sleeper.app/v1`` -- Sleeper's public API has no write
endpoints for third parties, and this client deliberately mirrors that: it
must never grow a write method.
"""

from typing import Any

import httpx

from ultimate_guillotine.sleeper.models import SleeperLeague, SleeperRoster, SleeperUser

BASE_URL = "https://api.sleeper.app/v1"

#: Sleeper's projections live outside the versioned API, so this one call uses an
#: absolute URL instead of the client's pinned ``base_url``. Verified 2026-09-09.
PROJECTIONS_URL = "https://api.sleeper.app/projections/nfl/{season}/{week}"

TIMEOUT = 10.0


class SleeperClient:
    """Thin wrapper over an ``httpx.Client`` for the Sleeper API.

    The provided ``httpx.Client`` is configured in place: its ``base_url``
    is pinned to Sleeper's API root, its timeout is set to ``TIMEOUT``
    seconds, and redirects are disabled so it can never be redirected off
    ``api.sleeper.app``.
    """

    def __init__(self, http: httpx.Client) -> None:
        http.base_url = BASE_URL
        http.timeout = TIMEOUT
        http.follow_redirects = False
        self._http = http

    def get_league(self, league_id: str) -> SleeperLeague:
        """Fetch league metadata (season, roster count, name)."""
        response = self._http.get(f"/league/{league_id}")
        response.raise_for_status()
        return SleeperLeague.model_validate(response.json())

    def get_users(self, league_id: str) -> list[SleeperUser]:
        """Fetch the league's member users."""
        response = self._http.get(f"/league/{league_id}/users")
        response.raise_for_status()
        return [SleeperUser.model_validate(item) for item in response.json()]

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        """Fetch the league's rosters (roster id to owner mapping)."""
        response = self._http.get(f"/league/{league_id}/rosters")
        response.raise_for_status()
        return [SleeperRoster.model_validate(item) for item in response.json()]

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        """Fetch raw matchup data for a given week."""
        response = self._http.get(f"/league/{league_id}/matchups/{week}")
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    def get_nfl_state(self) -> dict[str, Any]:
        """Fetch the current NFL season/week state."""
        response = self._http.get("/state/nfl")
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def get_players(self) -> dict[str, dict[str, Any]]:
        """Fetch the full NFL player directory, keyed by Sleeper player id.

        This payload is large and slow to generate, so it gets a longer
        timeout than the rest of the client's calls.
        """
        response = self._http.get("/players/nfl", timeout=60.0)
        response.raise_for_status()
        result: dict[str, dict[str, Any]] = response.json()
        return result

    def get_projections(self, season: int, week: int) -> list[dict[str, Any]]:
        """Fetch weekly player projections for ``season``/``week``.

        The endpoint sits outside ``/v1`` and answers with a JSON array of one
        object per player (roughly 9,400 rows, 5.6 MB), so it gets an absolute
        URL and the same longer timeout the player dump uses. Redirects stay
        disabled by the client's constructor.
        """
        response = self._http.get(
            PROJECTIONS_URL.format(season=season, week=week),
            params={"season_type": "regular"},
            timeout=60.0,
        )
        response.raise_for_status()
        payload: list[dict[str, Any]] = response.json()
        # The ``noqa: TRY004`` markers below waive ruff's preference for ``TypeError``:
        # a malformed remote body is a data error, not an argument error.
        if not isinstance(payload, list):
            raise ValueError("sleeper projections payload is not a list")  # noqa: TRY004
        if not payload:
            raise ValueError("sleeper projections payload is empty")
        for row in payload:
            if not isinstance(row, dict):
                raise ValueError("sleeper projections row is not an object")  # noqa: TRY004
            if not row.get("player_id"):
                raise ValueError("sleeper projections row has no player_id")
            if row.get("category") != "proj":
                raise ValueError("sleeper projections row is not category proj")
            if not isinstance(row.get("stats"), dict):
                raise ValueError("sleeper projections row has no stats object")  # noqa: TRY004
        return payload
