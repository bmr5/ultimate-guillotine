"""Historical league tools expose saved evidence without private database fields."""

from decimal import Decimal
from types import SimpleNamespace

from ultimate_guillotine.agent.tools.league import historical_roster, historical_transactions
from ultimate_guillotine.agent.tools.source import DatabaseSource


class Cursor:
    def __init__(self, batches):
        self.batches = batches
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query, params=()):
        self.calls.append((query, params))

    def fetchall(self):
        return self.batches.pop(0)


class Connection:
    def __init__(self, batches):
        self.cur = Cursor(batches)

    def cursor(self):
        return self.cur


def test_catalog_keeps_original_direction_in_announcement():
    conn = Connection([
        [(11, "Ben R"), (6, "Brandon L")],
        [("T-2025-041", 6, None, "permanent_faab_sale", "straight_purchase",
          [11, 6], [{"kind": "player", "name": "QJ"}], 111, "high",
          "QJ to Brandon for $111 - straight sale")],
    ])
    row = DatabaseSource(conn, None, "unused").catalog(2025)[0]
    assert row["parties"] == ["Ben R", "Brandon L"]
    assert row["announcement"] == "QJ to Brandon for $111 - straight sale"
    assert "announcement" in conn.cur.calls[1][0]


def test_saved_roster_search_returns_weekly_owner_and_player_score():
    conn = Connection([[(5, "Ben R", "Supreme Projections", Decimal("110.5"), {
        "starters": [{"player_id": "9754", "player_label": "Quentin Johnston",
                      "position": "WR", "slot": "FLEX", "points": 6.9}],
        "bench": [],
    })]])
    result = historical_roster(DatabaseSource(conn, None, "unused"), 2025,
                               player="Quentin Johnston")
    assert result["rows"][0]["member"] == "Ben R"
    assert result["rows"][0]["players"][0]["points"] == 6.9
    assert result["scope"].startswith("Saved competitive matchup rosters")


class Sleeper:
    def get_users(self, _league_id):
        return [SimpleNamespace(user_id="ben", display_name="benray887"),
                SimpleNamespace(user_id="brandon", display_name="SuperKing3")]

    def get_rosters(self, _league_id):
        return [SimpleNamespace(roster_id=1, owner_id="ben"),
                SimpleNamespace(roster_id=8, owner_id="brandon")]

    def get_transactions(self, _league_id, week):
        assert week == 5
        return [{"transaction_id": "trade-1", "type": "trade", "status": "complete",
                 "leg": 5, "created": 1759859097873,
                 "adds": {"9754": 8}, "drops": {"9754": 1}}]


def test_archived_sleeper_trade_names_sender_and_receiver():
    conn = Connection([
        [("league-2025",)],
        [(1, "Ben R"), (8, "Brandon L")],
        [("9754", "Quentin Johnston")],
    ])
    result = historical_transactions(DatabaseSource(conn, Sleeper(), "league-2026"),
                                     2025, week=5, player="Quentin Johnston")
    assert result["total_matches"] == 1
    assert result["transactions"][0]["moves"] == [
        {"member": "Brandon L", "adds": ["Quentin Johnston"], "drops": []},
        {"member": "Ben R", "adds": [], "drops": ["Quentin Johnston"]},
    ]
    assert "league-2025" not in str(result)
