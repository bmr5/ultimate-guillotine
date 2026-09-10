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

#: How much of a projections payload may be malformed before the payload itself is
#: the problem. A live week is roughly 9,400 rows and Sleeper does occasionally send
#: a handful of odd ones; refusing the week over three bad rows would leave the board
#: with no numbers at all, which is strictly worse than scoring the other 9,397.
MAX_DROPPED_PCT = 1


def _is_projection_row(row: Any) -> bool:
    """Is this one usable projection row?

    A row has to be an object, name a player, be a projection rather than a stat
    line, and carry a stats object. Anything else is dropped by
    :meth:`SleeperClient.get_projections` and counted there.
    """
    return (
        isinstance(row, dict)
        and bool(row.get("player_id"))
        and row.get("category") == "proj"
        and isinstance(row.get("stats"), dict)
    )


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

    def get_transactions(self, league_id: str, week: int) -> list[dict[str, Any]]:
        """Fetch the raw transactions -- adds, drops, waivers, trades -- for one week."""
        response = self._http.get(f"/league/{league_id}/transactions/{week}")
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

        **A malformed row is dropped, not fatal.** One unusable object out of 9,400
        used to refuse the whole week, which leaves the board with no projections at
        all -- a worse answer than the 9,399 good rows. Bad rows are counted instead,
        and only the shape of the *payload* refuses: an empty or non-array body, or
        more than ``MAX_DROPPED_PCT`` percent of rows dropped, which is a feed that
        has changed shape rather than a feed with a few odd players in it.

        A single dropped row is tolerated at any size, because one percent of a
        handful of rows is not a meaningful test. Nothing rests on that: a payload
        small enough for it to matter is refused by the thin-payload guard in
        ``fetch_projection_rows`` long before it can be written.
        """
        response = self._http.get(
            PROJECTIONS_URL.format(season=season, week=week),
            params={"season_type": "regular"},
            timeout=60.0,
        )
        response.raise_for_status()
        payload: list[Any] = response.json()
        # The ``noqa: TRY004`` marker below waives ruff's preference for ``TypeError``:
        # a malformed remote body is a data error, not an argument error.
        if not isinstance(payload, list):
            raise ValueError("sleeper projections payload is not a list")  # noqa: TRY004
        if not payload:
            raise ValueError("sleeper projections payload is empty")
        rows = [row for row in payload if _is_projection_row(row)]
        dropped = len(payload) - len(rows)
        if dropped > 1 and dropped * 100 > len(payload) * MAX_DROPPED_PCT:
            raise ValueError(
                f"sleeper projections payload dropped {dropped} malformed rows "
                f"of {len(payload)}"
            )
        return rows
