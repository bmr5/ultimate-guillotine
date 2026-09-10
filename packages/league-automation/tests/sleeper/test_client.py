import json
from pathlib import Path

import httpx
import pytest
import respx

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.models import SleeperLeague

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
    assert len(by_id[1].players) == 9
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


@respx.mock
def test_get_draft_parses_status_and_dimensions() -> None:
    respx.get("https://api.sleeper.app/v1/draft/1389372259260452865").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "draft_2026.json").read_text())
        )
    )
    draft = SleeperClient(httpx.Client()).get_draft("1389372259260452865")
    assert (draft.type, draft.status) == ("auction", "complete")
    assert (draft.teams, draft.rounds) == (18, 9)
    assert draft.started_at is not None and draft.started_at.year == 2026


@respx.mock
def test_get_draft_picks_returns_the_raw_list() -> None:
    respx.get("https://api.sleeper.app/v1/draft/1389372259260452865/picks").mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "draft_picks_2026.json").read_text())
        )
    )
    picks = SleeperClient(httpx.Client()).get_draft_picks("1389372259260452865")
    assert len(picks) == 162
    assert picks[0]["metadata"]["amount"] == "53"


@respx.mock
def test_get_transactions_asks_for_the_week() -> None:
    route = respx.get(
        "https://api.sleeper.app/v1/league/1389372259260452864/transactions/1"
    ).mock(
        return_value=httpx.Response(
            200, json=json.loads((FIXTURES / "transactions_2026_w1.json").read_text())
        )
    )
    records = SleeperClient(httpx.Client()).get_transactions("1389372259260452864", 1)
    assert route.called
    assert len(records) == 8
    assert {r["type"] for r in records} == {"trade", "free_agent"}


def test_the_league_fixture_names_its_draft() -> None:
    league = SleeperLeague.model_validate(
        json.loads((FIXTURES / "league_2026.json").read_text())
    )
    assert league.draft_id == "1389372259260452865"


@respx.mock
def test_get_schedule_reads_the_public_schedule_feed_off_the_versioned_api() -> None:
    """The schedule sits outside `/v1` like the projections, so it is an absolute URL:
    a relative path would resolve under the pinned base and 404."""
    route = respx.get("https://api.sleeper.app/schedule/nfl/regular/2026").mock(
        return_value=httpx.Response(
            200,
            json=[{"status": "pre_game", "date": "2026-09-13", "home": "CAR", "week": 1,
                   "game_id": "202610105", "away": "CHI"}],
        )
    )
    client = SleeperClient(httpx.Client())
    games = client.get_schedule(2026)
    assert route.called
    assert games[0]["home"] == "CAR"


@respx.mock
def test_get_schedule_refuses_a_body_that_is_not_a_list() -> None:
    respx.get("https://api.sleeper.app/schedule/nfl/regular/2026").mock(
        return_value=httpx.Response(200, json={"error": "nope"})
    )
    client = SleeperClient(httpx.Client())
    with pytest.raises(ValueError, match="not a list"):
        client.get_schedule(2026)
