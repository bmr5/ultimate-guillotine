import json
from pathlib import Path

import httpx
import pytest
import respx

from ultimate_guillotine.sleeper.client import SleeperClient

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "projections_2026_w1.json"
URL = "https://api.sleeper.app/projections/nfl/2026/1"


@respx.mock
def test_get_projections_uses_the_absolute_non_v1_url_and_regular_season_type() -> None:
    route = respx.get(URL).mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    rows = SleeperClient(httpx.Client()).get_projections(2026, 1)
    assert isinstance(rows, list) and len(rows) == 7
    assert {r["player_id"] for r in rows} >= {"4943", "SEA", "10881"}
    assert rows[0]["stats"]["pass_yd"] == 243.94
    request = route.calls.last.request
    assert str(request.url) == f"{URL}?season_type=regular"
    assert "/v1/" not in str(request.url)
    assert request.extensions["timeout"]["read"] == 60.0


@respx.mock
def test_get_projections_keeps_redirects_disabled() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text())))
    http = httpx.Client()
    SleeperClient(http).get_projections(2026, 1)
    assert http.follow_redirects is False


@respx.mock
def test_get_projections_raises_on_non_2xx() -> None:
    respx.get(URL).mock(return_value=httpx.Response(502))
    with pytest.raises(httpx.HTTPStatusError):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_non_list_payload() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"4943": {}}))
    with pytest.raises(ValueError, match="list"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


_MISSING = object()


def _row(**overrides: object) -> dict[str, object]:
    """One minimally valid projection row, with fields overridden or removed."""
    row: dict[str, object] = {
        "player_id": "4943",
        "category": "proj",
        "stats": {"pts_ppr": 17.11},
    }
    for key, value in overrides.items():
        if value is _MISSING:
            row.pop(key, None)
        else:
            row[key] = value
    return row


@respx.mock
def test_get_projections_rejects_an_empty_payload() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(ValueError, match="empty"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_row_that_is_not_an_object() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[_row(), "4943"]))
    with pytest.raises(ValueError, match="not an object"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_row_missing_player_id() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[_row(player_id=_MISSING)]))
    with pytest.raises(ValueError, match="player_id"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_row_with_a_blank_player_id() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[_row(player_id="")]))
    with pytest.raises(ValueError, match="player_id"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_row_whose_category_is_not_proj() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[_row(category="stat")]))
    with pytest.raises(ValueError, match="category proj"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_row_missing_stats() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[_row(stats=_MISSING)]))
    with pytest.raises(ValueError, match="stats"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_rejects_a_row_whose_stats_is_not_an_object() -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=[_row(stats=[])]))
    with pytest.raises(ValueError, match="stats"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)
