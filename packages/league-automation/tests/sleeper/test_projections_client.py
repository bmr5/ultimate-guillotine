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
