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


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("4943", id="not-an-object"),
        pytest.param(_row(player_id=_MISSING), id="no-player-id"),
        pytest.param(_row(player_id=""), id="blank-player-id"),
        pytest.param(_row(category="stat"), id="not-a-projection"),
        pytest.param(_row(stats=_MISSING), id="no-stats"),
        pytest.param(_row(stats=[]), id="stats-not-an-object"),
    ],
)
@respx.mock
def test_get_projections_drops_each_malformed_shape(malformed: object) -> None:
    """Every shape that used to refuse the week is now dropped from it. Refusing
    9,400 good rows over one bad one leaves the board with nothing at all."""
    respx.get(URL).mock(return_value=httpx.Response(200, json=[_row(), malformed]))

    assert SleeperClient(httpx.Client()).get_projections(2026, 1) == [_row()]


@respx.mock
def test_get_projections_keeps_the_good_rows_around_a_malformed_one() -> None:
    """One bad row among the fixture's seven: the other six come back."""
    payload = json.loads(FIXTURE.read_text())
    payload[3] = "not a row"
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    rows = SleeperClient(httpx.Client()).get_projections(2026, 1)

    assert len(rows) == 6
    assert all(isinstance(row, dict) for row in rows)


@respx.mock
def test_get_projections_refuses_a_payload_that_is_mostly_malformed() -> None:
    """Past one percent it is not a few odd players, it is a feed that has changed
    shape, and scoring what is left would silently understate the whole week."""
    payload = [_row(player_id=str(n)) for n in range(92)] + [_row(category="stat")] * 8
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(ValueError, match="dropped 8 malformed rows of 100"):
        SleeperClient(httpx.Client()).get_projections(2026, 1)


@respx.mock
def test_get_projections_allows_exactly_one_percent_dropped() -> None:
    payload = [_row(player_id=str(n)) for n in range(198)] + [_row(category="stat")] * 2
    respx.get(URL).mock(return_value=httpx.Response(200, json=payload))

    assert len(SleeperClient(httpx.Client()).get_projections(2026, 1)) == 198
