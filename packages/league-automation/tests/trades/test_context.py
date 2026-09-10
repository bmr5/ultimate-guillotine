"""The context pack: what it says, what it must never say, and how big it gets."""

from decimal import Decimal

import pytest

from ultimate_guillotine.advisor.state import AdvisorHolding, AdvisorTeamState, LeagueSnapshot
from ultimate_guillotine.trades.context import (
    CONTEXT_CHAR_BUDGET,
    TRADE_LIMIT,
    ContextPlayer,
    ContextTeam,
    build_registrar_context,
    context_from_snapshot,
)
from ultimate_guillotine.trades.models import MemberRef

TEAMS = (
    ContextTeam(
        username="Member01",
        aliases=("m1", "memberone"),
        faab_remaining=340,
        players=(
            ContextPlayer("Player Beta", "RB"),
            ContextPlayer("Player Alpha", "QB"),
            ContextPlayer("Kansas City Chiefs", "DEF"),
            ContextPlayer("Player Gamma", "WR"),
        ),
    ),
    ContextTeam(
        username="Member02",
        faab_remaining=0,
        players=(ContextPlayer("Player Delta", "TE"),),
        is_eliminated=True,
        eliminated_week=5,
    ),
)


def trade(**overrides) -> dict:
    base = {
        "trade_id": 1,
        "trade_code": "T-2026-004",
        "status": "accepted",
        "revision": 1,
        "effective_week": 3,
        "terms": {
            "parties": [
                {"member_id": 1, "display_name": "Member01"},
                {"member_id": 2, "display_name": "Member02"},
            ],
            "assets": [
                {
                    "kind": "player",
                    "from_member_id": 1,
                    "to_member_id": 2,
                    "player_id": "p1",
                    "player_name": "Player Alpha",
                    "amount": None,
                    "unit": None,
                    "description": None,
                },
                {
                    "kind": "faab",
                    "from_member_id": 2,
                    "to_member_id": 1,
                    "player_id": None,
                    "player_name": None,
                    "amount": 450,
                    "unit": "faab",
                    "description": None,
                },
            ],
            "evidence_excerpt": "🚨 Trade Alert 🚨 the announcement as somebody typed it",
        },
    }
    return {**base, **overrides}


def test_the_pack_names_the_week_the_rosters_the_faab_and_the_trades() -> None:
    pack = build_registrar_context(3, TEAMS, [trade()])
    assert "Current NFL week: 3" in pack
    assert "Rosters:" in pack and "FAAB remaining:" in pack
    assert "Trades this season:" in pack
    assert pack.index("Current NFL week") < pack.index("Rosters:") < pack.index("FAAB remaining:")


def test_a_roster_line_is_the_username_the_nicknames_and_the_players_in_position_order() -> None:
    """The username is the join key the `League members` line uses, so a player
    the model copies out of this section lands next to a party code can resolve."""
    line = _line(build_registrar_context(3, TEAMS, []), "Member01")
    assert line == (
        "Member01 (m1, memberone): Player Alpha QB, Player Beta RB, Player Gamma WR, "
        "Kansas City Chiefs DEF"
    )


def test_a_manager_with_no_nicknames_says_so_rather_than_showing_empty_brackets() -> None:
    assert _line(build_registrar_context(3, TEAMS, []), "Member02").startswith(
        "Member02 (no known nicknames)"
    )


def test_an_eliminated_team_stays_in_the_pack_and_is_marked_with_its_week() -> None:
    """Its players are still tradeable, so leaving the team out would make a real
    trade unresolvable; leaving the mark out would hide why its FAAB is frozen."""
    assert "(eliminated wk 5)" in _line(build_registrar_context(3, TEAMS, []), "Member02")


def test_an_elimination_with_no_recorded_week_is_still_marked() -> None:
    teams = (ContextTeam(username="Member03", is_eliminated=True),)
    assert "(eliminated)" in build_registrar_context(3, teams, [])
    assert "wk None" not in build_registrar_context(3, teams, [])


def test_faab_is_one_line_a_team() -> None:
    pack = build_registrar_context(3, TEAMS, [])
    faab = pack.split("FAAB remaining:\n")[1]
    assert faab.splitlines()[:2] == ["Member01: $340", "Member02: $0"]


def test_a_trade_line_carries_the_code_week_status_and_both_legs() -> None:
    line = _line(build_registrar_context(3, TEAMS, [trade()]), "T-2026-004")
    assert line == (
        "T-2026-004 wk3 accepted: Member01 → Member02: Player Alpha; "
        "Member02 → Member01: 450 FAAB"
    )


def test_a_rescinded_trade_is_marked_by_its_status() -> None:
    """The code is what a follow-up rescission or revision names, so a rescinded
    trade has to stay listed -- with the fact that it is already off."""
    assert "rescinded:" in build_registrar_context(3, TEAMS, [trade(status="rescinded")])


def test_a_trade_with_no_stated_week_says_so_rather_than_printing_none() -> None:
    assert "wk?" in build_registrar_context(3, TEAMS, [trade(effective_week=None)])


def test_the_pack_never_carries_the_announcement_text() -> None:
    """The pack rides along with a message from a private chat. Terms are what
    the rules need; twenty-five old announcements are not, and re-feeding them
    would widen one prompt's exposure from one message to a season of them."""
    pack = build_registrar_context(3, TEAMS, [trade()])
    assert "the announcement as somebody typed it" not in pack
    assert "evidence_excerpt" not in pack


def test_only_the_newest_trades_are_carried() -> None:
    trades = [trade(trade_code=f"T-2026-{i:03d}") for i in range(1, TRADE_LIMIT + 6)]
    pack = build_registrar_context(3, TEAMS, trades)
    assert pack.count("wk3 accepted") == TRADE_LIMIT
    assert "T-2026-001" in pack and f"T-2026-{TRADE_LIMIT + 5:03d}" not in pack


def test_a_trade_whose_terms_name_no_assets_is_left_out() -> None:
    """A code with nothing after it tells the model nothing and invites it to
    guess what the trade was."""
    pack = build_registrar_context(3, (), [trade(terms={"parties": [], "assets": []})])
    assert "Trades this season" not in pack


@pytest.mark.parametrize(
    ("unit", "amount", "expected"),
    [("faab", 450, "450 FAAB"), ("usd", 25, "$25"), ("draft_dollars", 30, "30 draft dollars")],
)
def test_every_money_unit_is_spelled_the_way_the_chat_spells_it(
    unit: str, amount: int, expected: str
) -> None:
    terms = {
        "parties": [{"member_id": 1, "display_name": "Member01"}],
        "assets": [
            {"kind": unit, "from_member_id": 1, "to_member_id": None, "amount": amount,
             "unit": unit, "player_name": None, "player_id": None, "description": None}
        ],
    }
    assert expected in build_registrar_context(3, (), [trade(terms=terms)])


def test_a_league_the_data_layer_cannot_describe_renders_nothing() -> None:
    """Better an absent section than `Rosters:` over nothing, which reads as a
    league where every roster is empty."""
    assert build_registrar_context(None, (), []) == ""


def test_a_full_league_fits_the_prompt_budget() -> None:
    """18 teams, 16 players each, 25 trades -- the pack the league will actually
    produce -- must stay a fraction of the prompt rather than dominate it."""
    teams = tuple(
        ContextTeam(
            username=f"Member{i:02d}",
            aliases=("a nickname", "another nickname"),
            faab_remaining=1000 - i,
            players=tuple(
                ContextPlayer(f"Firstname{i:02d} Surnameiswordy{j:02d}", "WR") for j in range(16)
            ),
        )
        for i in range(18)
    )
    trades = [trade(trade_code=f"T-2026-{i:03d}") for i in range(TRADE_LIMIT)]
    pack = build_registrar_context(9, teams, trades)
    assert len(pack) < CONTEXT_CHAR_BUDGET, len(pack)


def test_the_snapshot_adapter_reads_rosters_faab_and_the_week() -> None:
    """The registrar and the CLI build the pack from the Advisor's one league
    read rather than from a second set of queries against the same tables."""
    pack = context_from_snapshot(
        _snapshot(),
        [MemberRef(1, "Member01", ("m1",)), MemberRef(2, "Member02", ())],
        [trade()],
    )
    assert "Current NFL week: 6" in pack
    assert "Member01 (m1): Player Alpha QB" in pack
    assert "Member01: $340" in pack
    assert "(eliminated wk 4)" in pack


def _snapshot() -> LeagueSnapshot:
    from datetime import UTC, datetime

    at = datetime(2026, 9, 9, tzinfo=UTC)

    def team(
        member_id: int, name: str, player: str, position: str,
        eliminated: bool = False, eliminated_week: int | None = None,
    ) -> AdvisorTeamState:
        return AdvisorTeamState(
            team_id=100 + member_id,
            member_id=member_id,
            display_name=name,
            member_label=name,
            team_name=f"Team {member_id}",
            sleeper_roster_id=member_id,
            faab_remaining=340,
            elimination_source=None,
            week=6,
            projected_points={},
            coverage_pct=Decimal("100.00"),
            is_provisional=False,
            holdings=(
                AdvisorHolding(
                    sleeper_player_id="p1",
                    player_name=player,
                    position=position,
                    slot="starter",
                    lineup_position=position,
                    slot_index=0,
                    week=6,
                    projected_points={},
                ),
            ),
            is_eliminated=eliminated,
            eliminated_week=eliminated_week,
        )

    return LeagueSnapshot(
        season=2026,
        season_id=1,
        week=6,
        weeks=(6,),
        synced_at=at,
        oldest_synced_at=at,
        teams=(
            team(1, "Member01", "Player Alpha", "QB"),
            team(2, "Member02", "Player Delta", "TE", eliminated=True, eliminated_week=4),
        ),
    )


def _line(pack: str, starts_with: str) -> str:
    return next(line for line in pack.splitlines() if line.startswith(starts_with))
