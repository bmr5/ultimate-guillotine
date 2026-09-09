import json
from pathlib import Path

import httpx
import respx

from ultimate_guillotine.sleeper.client import SleeperClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sleeper"


@respx.mock
def test_get_league_parses_roster_count() -> None:
    respx.get("https://api.sleeper.app/v1/league/1389372259260452864").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "league_2026.json").read_text()))
    )
    client = SleeperClient(httpx.Client())
    league = client.get_league("1389372259260452864")
    assert league.season == "2026"
    assert league.season_year == 2026
    assert league.total_rosters == 18


@respx.mock
def test_get_users_parses_display_names() -> None:
    respx.get("https://api.sleeper.app/v1/league/1389372259260452864/users").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "users_2026.json").read_text()))
    )
    client = SleeperClient(httpx.Client())
    users = client.get_users("1389372259260452864")
    assert len(users) == 18
    assert users[0].display_name == "Member01"


@respx.mock
def test_get_rosters_parses_owner_ids() -> None:
    respx.get("https://api.sleeper.app/v1/league/1389372259260452864/rosters").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "rosters_2026.json").read_text()))
    )
    client = SleeperClient(httpx.Client())
    rosters = client.get_rosters("1389372259260452864")
    assert len(rosters) == 18
    assert rosters[0].owner_id == "user-01"


@respx.mock
def test_get_rosters_reads_players_from_a_list_or_null() -> None:
    """Sleeper sends ``"players": null`` for an empty roster; that is not an error."""
    respx.get("https://api.sleeper.app/v1/league/1389372259260452864/rosters").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "rosters_2026.json").read_text()))
    )
    client = SleeperClient(httpx.Client())
    by_id = {r.roster_id: r for r in client.get_rosters("1389372259260452864")}
    assert by_id[1].players[:2] == ["4034", "6794"]
    assert by_id[2].players == []


@respx.mock
def test_get_league_raises_on_http_error() -> None:
    respx.get("https://api.sleeper.app/v1/league/bad-id").mock(return_value=httpx.Response(404))
    client = SleeperClient(httpx.Client())
    try:
        client.get_league("bad-id")
    except httpx.HTTPStatusError:
        pass
    else:
        raise AssertionError("expected HTTPStatusError")


def test_client_exposes_no_write_methods() -> None:
    write_verbs = {"post", "put", "patch", "delete", "create", "update"}
    public_methods = {name for name in dir(SleeperClient) if not name.startswith("_")}
    for method in public_methods:
        assert not any(verb in method.lower() for verb in write_verbs), method


def test_client_does_not_follow_redirects_off_sleeper() -> None:
    client = SleeperClient(httpx.Client())
    assert client._http.follow_redirects is False
