import json
from pathlib import Path

import pytest

from ultimate_guillotine.trades.detect import is_rescission_candidate, is_trade_candidate

ALERTS = json.loads((Path(__file__).parent.parent / "fixtures" / "trades" / "alerts.json").read_text())


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
