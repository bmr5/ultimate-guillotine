"""Facts are checked against the league; structure is never judged."""

from ultimate_guillotine.advisor.fixture import fixture_snapshot
from ultimate_guillotine.agent.answer import LeagueAnswer
from ultimate_guillotine.agent.artifact import ARTIFACT_MAX_BYTES
from ultimate_guillotine.agent.tools.source import FixtureSource
from ultimate_guillotine.agent.verify import privacy_problems, verify
from ultimate_guillotine.trades.models import MemberRef

SNAPSHOT = fixture_snapshot()
SOURCE = FixtureSource()
MEMBERS = [MemberRef(t.member_id, f"joinkey{t.member_id:02d}", (), nickname=t.member_label)
           for t in SNAPSHOT.teams]
PLAYERS = SOURCE.players()


def _answer(**overrides) -> LeagueAnswer:
    base = {
        "kind": "answer",
        "chat_text": "Member02 could hold Bench 05-0 for 40 FAAB.",
        "report": None,
        "facts": {
            "players": [{"player_id": "p05b0", "name": "Bench 05-0", "holder": "Member05"}],
            "faab": [{"member": "Member05", "amount": 800, "claim": "balance"},
                     {"member": "Member05", "amount": 40, "claim": "offer"}],
            "proposals": [{
                "title": "Hold", "counterparties": ["Member02"],
                "legs": [
                    {"kind": "player", "player_id": "p05b0", "player_name": "Bench 05-0",
                     "from_member": "Member05", "to_member": "Member02"},
                    {"kind": "faab", "amount": 40, "from_member": "Member05",
                     "to_member": "Member02"},
                    {"kind": "term", "text": "returns before the Week 7 lock",
                     "from_member": "Member02", "to_member": "Member05"},
                ],
            }],
        },
        "source_line": "Source: rosters as of 3:00pm",
    }
    return LeagueAnswer.model_validate({**base, **overrides})


def _check(answer: LeagueAnswer, **kw) -> list[str]:
    return verify(answer, SNAPSHOT, MEMBERS, PLAYERS, **kw)


def test_a_true_answer_passes() -> None:
    assert _check(_answer()) == []


def test_a_player_on_the_wrong_roster_is_named() -> None:
    wrong = _answer(facts={"players": [{"player_id": "p05b0", "name": "Bench 05-0",
                                         "holder": "Member02"}]})
    problems = _check(wrong)
    assert problems == ["Bench 05-0 is on Member05's roster, not Member02's"]


def test_a_free_agent_claim_is_checked_both_ways() -> None:
    assert _check(_answer(facts={"players": [{"player_id": "fa1", "name": "Free Agent One",
                                              "holder": "free agent"}]})) == []
    problems = _check(_answer(facts={"players": [{"player_id": "p05b0", "name": "Bench 05-0",
                                                  "holder": "free agent"}]}))
    assert "not a free agent" in problems[0]


def test_faab_balances_must_match_and_offers_must_fit() -> None:
    off = _answer(facts={"faab": [{"member": "Member05", "amount": 801, "claim": "balance"}]})
    assert _check(off) == ["Member05's FAAB is 800, not 801"]
    big = _answer(facts={"faab": [{"member": "Member05", "amount": 900, "claim": "offer"}]})
    assert _check(big) == ["an offer of 900 FAAB is over Member05's budget of 800"]


def test_an_eliminated_counterparty_and_a_leg_from_the_wrong_roster_fail() -> None:
    dead = _answer(facts={"proposals": [{"title": "x", "counterparties": ["Member17"],
                                         "legs": [{"kind": "term", "text": "t",
                                                   "from_member": "Member17",
                                                   "to_member": "Member05"}]}]})
    assert _check(dead) == ["Member17 is eliminated and cannot be a counterparty"]
    wrong = _answer(facts={"proposals": [{"title": "x", "counterparties": ["Member02"],
                                          "legs": [{"kind": "player", "player_name": "Bench 05-0",
                                                    "from_member": "Member02",
                                                    "to_member": "Member05"}]}]})
    assert _check(wrong) == ["Bench 05-0 is on Member05's roster, not Member02's"]


def test_sources_must_be_https_and_the_artifact_must_fit() -> None:
    report = {"title": "t", "question": "q", "html_body": "<p>x</p>",
              "sources": [{"url": "http://example.com/x", "claim": "c"}]}
    assert _check(_answer(report=report)) == ["source is not https: http://example.com/x"]
    assert _check(_answer(), artifact_bytes=ARTIFACT_MAX_BYTES + 1) == [
        "the write-up is over 200000 bytes"
    ]


def test_the_privacy_scan_catches_what_may_never_be_said() -> None:
    assert privacy_problems("call +1 (555) 555-0100", MEMBERS) == ["a phone number"]
    assert privacy_problems("mail ben@example.com", MEMBERS) == ["an email address"]
    assert privacy_problems("iMessage;+;chat-x", MEMBERS) == ["a chat identifier"]
    assert privacy_problems("a" * 64, MEMBERS) == ["a hash"]
    assert privacy_problems("dues are late", MEMBERS) == ["dues"]
    assert privacy_problems("joinkey05 is thin at RB", MEMBERS) == ["a member's join key"]
    assert privacy_problems("Member05 is thin at RB", MEMBERS) == []
    assert _check(_answer(chat_text="dues: see joinkey05")) == [
        "the chat text mentions dues", "the chat text mentions a member's join key"
    ]
    assert _check(_answer(), artifact_text="mail ben@example.com") == [
        "the write-up mentions an email address"
    ]
