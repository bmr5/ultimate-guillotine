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


def test_detection_is_case_and_inflection_insensitive() -> None:
    assert is_trade_candidate("🚨 MEMBER01 TRADED Player Alpha to member02")
    assert is_trade_candidate("🚨 member03 is renting Player Beta from member04 for 20 faab")
    # Siren plus an inflected trade word ("sending") is enough to flag this as a
    # candidate; the model's own "not_a_trade" classification is the second gate
    # that filters out messages like this one downstream.
    assert is_trade_candidate("🚨 who is sending the trophy pics") is True


def test_header_requires_whitespace() -> None:
    # "TradeAlert" as one word does not match; whitespace is required
    assert not is_trade_candidate("🚨 TradeAlert nothing else")


def test_a_rescission_term_alone_makes_a_candidate() -> None:
    """`🚨 Cancel T-2026-014 🚨` names no trade word at all, but it is exactly the
    message the registrar has to act on."""
    assert is_trade_candidate("🚨 Cancel T-2026-014 🚨") is True
    assert is_rescission_candidate("🚨 Cancel T-2026-014 🚨") is True
    assert is_trade_candidate("🚨 that deal is void 🚨") is True


#: Messages with no siren in them: what a group chat actually looks like, and the
#: one alert shape that started this rule. Kept as a table so a rule that gets
#: quietly widened fails under the name of the message it should have kept out.
NO_SIREN = [
    ("a header with no siren", "Trade Alert\nMember01 sends Player Alpha to Member02", True),
    (
        "a buy priced in FAAB",
        "Member01 buys Player Alpha from Member02 for $65 FAAB ($13 draft FAAB)",
        True,
    ),
    ("a sale priced in dollars", "Member03 sells Player Beta to Member04 for $40", True),
    ("a rental", "Member01 sends Player Gamma to Member02 as a 1 week rental", True),
    ("a pick", "Member02 trades Player Delta for a 3rd round pick", True),
    ("a verb with nothing being paid", "Member01 sends Player Alpha to Member02", False),
    ("talking about trading", "anyone want to trade for a WR", False),
    ("a price with no verb", "my FAAB is down to 40", False),
    ("the word for on its own", "thanks for the assist", False),
    ("banter that mentions a trade", "that trade was highway robbery lmao", False),
]


@pytest.mark.parametrize(("name", "text", "expected"), NO_SIREN, ids=[n for n, _, _ in NO_SIREN])
def test_a_message_with_no_siren_needs_a_header_or_a_verb_and_a_price(
    name: str, text: str, expected: bool
) -> None:
    """The 🚨 is the strongest signal, not the only one.

    A real alert -- `Member01 buys Player Alpha from Member02 for $65 FAAB` --
    reached the chat with no siren on it and was never put to the model at all.
    Without a siren the message has to carry either an unmistakable header or
    both halves of a transaction: something that moves, and something that pays.
    """
    assert is_trade_candidate(text) is expected


def test_a_rescission_still_needs_its_siren() -> None:
    """The rescission path acts before any model call, so a false positive here
    un-logs a real trade rather than costing an extraction."""
    assert is_rescission_candidate("Cancel T-2026-014") is False
    assert is_rescission_candidate("🚨 Cancel T-2026-014") is True


def test_the_siren_rules_are_unchanged() -> None:
    """Widening the no-siren case must not narrow the siren case: a 🚨 message
    still only needs one trade word, a header, or a rescission word."""
    assert is_trade_candidate("🚨 Member03 rented for 10") is True
    assert is_trade_candidate("🚨 huge game tonight") is False
