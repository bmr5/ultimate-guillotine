import json
from pathlib import Path

import pytest

from ultimate_guillotine.trades.detect import is_rescission_candidate, is_trade_candidate

ALERTS = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "trades" / "alerts.json").read_text()
)


@pytest.mark.parametrize("alert", ALERTS, ids=[a["id"] for a in ALERTS])
def test_candidate_detection_matches_fixture(alert: dict) -> None:
    assert is_trade_candidate(alert["text"]) is alert["expect_candidate"]
    assert is_rescission_candidate(alert["text"]) is alert["expect_rescission"]


def test_the_word_trade_beside_the_siren_makes_a_candidate() -> None:
    """Ben (2026-09-10): the siren and the word trade, next to each other."""
    assert is_trade_candidate("🚨 Trade alert 🚨\nMax agrees to go to gulag for Ben for $200")
    assert is_trade_candidate("Trade alert 🚨\n\nDerek sends a 1 week Rhamondre rental to Charlie")
    assert is_trade_candidate("🚨 MEMBER01 TRADED Player Alpha to member02")
    assert is_trade_candidate("🚨 trade: Member01 sends Player Alpha to Member02")
    assert is_trade_candidate("🚨 TradeAlert nothing else")


def test_a_siren_without_trade_beside_it_is_not_a_candidate() -> None:
    """A rental, a sale or a shout under a siren is not marked as a trade; the
    announcer re-posts it with the word. The trade word on another line does
    not count either -- "next to" means on the line with the siren."""
    assert not is_trade_candidate("🚨 member03 is renting Player Beta from member04 for 20 faab")
    assert not is_trade_candidate("🚨 who is sending the trophy pics")
    assert not is_trade_candidate("🚨 Member01 sends Player Alpha to Member02 for 20 FAAB")
    assert not is_trade_candidate("🚨🚨🚨 FAAB 🚨🚨🚨")
    assert not is_trade_candidate("🚨 heads up\n\nTrade alert: Member01 buys Player Alpha")
    # Fifteen characters is "alert" and a colon, not a sentence between them.
    assert not is_trade_candidate("🚨 in a totally unrelated message trade is mentioned")


def test_a_rescission_term_alone_makes_a_candidate() -> None:
    """`🚨 Cancel T-2026-014 🚨` names no trade word at all, but it is exactly the
    message the registrar has to act on."""
    assert is_trade_candidate("🚨 Cancel T-2026-014 🚨") is True
    assert is_rescission_candidate("🚨 Cancel T-2026-014 🚨") is True
    assert is_trade_candidate("🚨 that deal is void 🚨") is True


#: Messages with no siren in them: what a group chat actually looks like, and the
#: one alert shape that started this rule. Kept as a table so a rule that gets
#: quietly widened fails under the name of the message it should have kept out.


@pytest.mark.parametrize(
    "text",
    [
        "Trade alert: Member01 buys Player Alpha from Member02 for $65 FAAB",
        "Member01 sends Player Alpha to Member02 for 300 FAAB",
        "Member01 buys Player Alpha from Member02 for $13 (draft dollars)",
        "anyone want to trade for a WR",
    ],
)
def test_without_a_siren_nothing_is_a_candidate(text: str) -> None:
    """Ben (2026-09-10): trades are explicitly marked with the siren. A message
    that reads exactly like an alert but carries no 🚨 is never put to the
    model; the siren is the league's own signal, not a hint."""
    assert is_trade_candidate(text) is False
    # With the siren, only the messages that put the word trade beside it count.
    assert is_trade_candidate("🚨 " + text) is text.startswith("Trade alert")


def test_a_rescission_still_needs_its_siren() -> None:
    """The rescission path acts before any model call, so a false positive here
    un-logs a real trade rather than costing an extraction."""
    assert is_rescission_candidate("Cancel T-2026-014") is False
    assert is_rescission_candidate("🚨 Cancel T-2026-014") is True


def test_the_siren_rules_are_unchanged() -> None:
    """A 🚨 message needs the word trade beside the siren, or a rescission word."""
    assert is_trade_candidate("🚨 Member03 rented for 10") is False
    assert is_trade_candidate("🚨 huge game tonight") is False
    assert is_trade_candidate("🚨 Void T-2026-006 🚨") is True
