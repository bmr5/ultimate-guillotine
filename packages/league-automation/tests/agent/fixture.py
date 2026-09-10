"""The agent fixture league and fabricated trade-price history for tests."""

from ultimate_guillotine.agent.tools.fixture import (
    ASKER_MEMBER_ID,
    BENCH,
    ELIMINATED_MEMBER_ID,
    FIXTURE_SEASON,
    FIXTURE_SEASON_ID,
    FIXTURE_SYNCED_AT,
    LINEUP,
    NEAR_CUT_MEMBER_ID,
    ROTATION,
    fixture_snapshot,
)
from ultimate_guillotine.agent.tools.pricing import PricePoint, price_points

__all__ = [
    "ASKER_MEMBER_ID",
    "BENCH",
    "ELIMINATED_MEMBER_ID",
    "FIXTURE_SEASON",
    "FIXTURE_SEASON_ID",
    "FIXTURE_SYNCED_AT",
    "HISTORY_SEASON",
    "LINEUP",
    "NEAR_CUT_MEMBER_ID",
    "PERMANENT_CODE",
    "PERMANENT_FAAB",
    "PERMANENT_ROW",
    "RENTAL_CODE",
    "RENTAL_FAAB",
    "RENTAL_ROW",
    "ROTATION",
    "fixture_snapshot",
    "price_history",
    "trade_row",
]

#: The season every fabricated price point is set in, so "newest first" is a
#: tie the trade code breaks rather than a season the fixture has to move.
HISTORY_SEASON = 2026

#: One permanent sale and one rental, both of a running back. The rental is the
#: cheaper of the two on purpose: a price read out of the wrong population is
#: then a number the test can see rather than a coincidence it cannot.
PERMANENT_CODE = "T-2026-001"
PERMANENT_FAAB = 80
RENTAL_CODE = "T-2026-002"
RENTAL_FAAB = 30



def trade_row(
    *,
    code: str,
    faab: int,
    player_id: str,
    player_name: str,
    kind: str = "permanent",
    seller: int = 1,
    buyer: int = 2,
    season: int = HISTORY_SEASON,
) -> dict:
    """One accepted trade: ``seller`` sent one player, ``buyer`` sent FAAB back.

    The simplest shape that prices anything -- one player, one payment -- so the
    price point is the whole of the FAAB and a test never has to reason about
    how a package splits.
    """
    return {
        "trade_code": code,
        "season": season,
        "terms": {
            "kind": kind,
            "effective_week": 4,
            "assets": [
                {
                    "kind": "player",
                    "from_member_id": seller,
                    "to_member_id": buyer,
                    "player_id": player_id,
                    "player_name": player_name,
                    "amount": None,
                    "unit": None,
                    "description": None,
                },
                {
                    "kind": "faab",
                    "from_member_id": buyer,
                    "to_member_id": seller,
                    "player_id": None,
                    "player_name": None,
                    "amount": faab,
                    "unit": "faab",
                    "description": None,
                },
            ],
            "parties": [],
            "special_terms": [],
        },
    }


def price_history(rows: list[dict]) -> list[PricePoint]:
    """These trade rows as price points, with positions read off the fixture."""
    snapshot = fixture_snapshot()
    positions = {h.sleeper_player_id: h.position for t in snapshot.teams for h in t.holdings}
    return price_points(rows, positions)


#: A permanent sale of a running back, at :data:`PERMANENT_FAAB`.
PERMANENT_ROW = trade_row(
    code=PERMANENT_CODE, faab=PERMANENT_FAAB, player_id="p01b0", player_name="Bench 01-0"
)
#: The same position, borrowed rather than bought, at :data:`RENTAL_FAAB`.
RENTAL_ROW = trade_row(
    code=RENTAL_CODE,
    faab=RENTAL_FAAB,
    player_id="p02b0",
    player_name="Bench 02-0",
    kind="rental",
    seller=2,
    buyer=1,
)
