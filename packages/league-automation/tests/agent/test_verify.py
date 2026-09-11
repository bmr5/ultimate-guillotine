"""Facts are checked against the league; structure is never judged."""

from dataclasses import replace

from ultimate_guillotine.agent.answer import LeagueAnswer
from ultimate_guillotine.agent.artifact import ARTIFACT_MAX_BYTES
from ultimate_guillotine.agent.tools.fixture import fixture_snapshot
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


def _money(amount, sender="Member05", recipient="Member02", kind="faab"):
    return {"kind": kind, "amount": amount, "from_member": sender, "to_member": recipient}


def _proposal(legs):
    return {"title": "Alternative", "counterparties": ["Member02"], "legs": legs}


def test_proposal_net_budget_sums_legs_but_not_alternatives():
    split = _proposal([_money(500), _money(500, recipient="Member03")])
    assert _check(_answer(facts={"proposals": [split]}))
    draft = _proposal([_money(100, kind="draft_dollars"), _money(301)])
    assert _check(_answer(facts={"proposals": [draft]}))
    credited = _proposal([_money(900), _money(200, sender="Member02", recipient="Member05")])
    assert _check(_answer(facts={"proposals": [credited]})) == []
    assert _check(_answer(facts={"proposals": [_proposal([_money(500)])] * 2})) == []


def test_player_id_and_name_must_agree_in_facts_and_legs():
    assert _check(_answer(facts={"players": [{
        "player_id": "p05b0", "name": "Starter 02-0", "holder": "Member05",
    }]}))
    leg = {"kind": "player", "player_id": "p05b0", "player_name": "Starter 02-0",
           "from_member": "Member05", "to_member": "Member02"}
    assert _check(_answer(facts={"proposals": [_proposal([leg])]}))
    leg["player_name"] = "bench 05-0"
    leg["from_member"] = "Fifth team"
    aliases = [replace(m, aliases=("Fifth team",)) if m.member_id == 5 else m for m in MEMBERS]
    assert verify(_answer(facts={"proposals": [_proposal([leg])]}),
                  SNAPSHOT, aliases, PLAYERS) == []


def test_every_leg_resolves_both_participants_even_when_not_listed():
    for recipient in ("Member17", "Nobody"):
        for leg in (
            _money(40, recipient=recipient),
            {"kind": "term", "text": "an option", "from_member": "Member05",
             "to_member": recipient},
            {"kind": "player", "player_id": "p05b0", "from_member": "Member05",
             "to_member": recipient},
        ):
            assert _check(_answer(facts={"proposals": [_proposal([leg])]}))


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


# The league's shape: a team's ``display_name`` is its join key, so the key resolves;
# the fixture's equals its label, which is why a bare join key there does not.
JOIN_KEYED = replace(SNAPSHOT, teams=tuple(
    replace(t, display_name=f"joinkey{t.member_id:02d}") for t in SNAPSHOT.teams
))
# Two members answering to one alias: what makes a token ambiguous.
TWINS = [replace(m, aliases=("Twin",)) if m.member_id in (2, 5) else m for m in MEMBERS]
UNPUBLISHED = "a check failed on a fact that named something the league does not publish"


def test_the_join_key_scan_matches_phrases_and_possessives() -> None:
    members = [*MEMBERS, MemberRef(99, "Ben Ray", (), nickname="Other Ben")]
    assert privacy_problems("Ben Ray is thin at RB", members) == ["a member's join key"]
    assert privacy_problems("Other Ben is thin at RB", members) == []
    assert privacy_problems("Ben is thin at RB", members) == []
    assert privacy_problems("joinkey05's roster", MEMBERS) == ["a member's join key"]
    assert privacy_problems("joinkey05’s roster", MEMBERS) == ["a member's join key"]
    assert privacy_problems("Member05's roster", MEMBERS) == []


def test_a_join_key_written_as_a_holder_is_never_echoed() -> None:
    fact = {"player_id": "p05b0", "name": "Bench 05-0", "holder": "joinkey02"}
    resolved = verify(_answer(facts={"players": [fact]}), JOIN_KEYED, MEMBERS, PLAYERS)
    assert resolved == ["Bench 05-0 is on Member05's roster, not Member02's"]
    unresolved = _check(_answer(facts={"players": [{**fact, "holder": "joinkey05"}]}))
    assert unresolved == [
        "the holder given for Bench 05-0 matches no member; name members by their league label"
    ]
    assert "joinkey" not in " ".join(resolved + unresolved)


def test_an_unresolvable_holder_gets_a_token_free_sentence() -> None:
    fact = {"player_id": "p05b0", "name": "Bench 05-0", "holder": "Nobody"}
    assert _check(_answer(facts={"players": [fact]})) == [
        "the holder given for Bench 05-0 matches no member; name members by their league label"
    ]
    twin = _answer(facts={"players": [{**fact, "holder": "Twin"}]})
    assert verify(twin, SNAPSHOT, TWINS, PLAYERS) == [
        "the holder given for Bench 05-0 could mean more than one member; ask which"
    ]


def test_every_member_slot_gets_the_same_token_free_shapes() -> None:
    faab = _answer(facts={"faab": [{"member": "Nobody", "amount": 800, "claim": "balance"}]})
    assert _check(faab) == [
        "the member given for a FAAB figure matches no member; name members by their league label"
    ]
    proposal = {"title": "x", "counterparties": ["Nobody"],
                "legs": [{"kind": "player", "player_name": "Bench 05-0",
                          "from_member": "Nobody", "to_member": "Member02"},
                         {"kind": "faab", "amount": 40,
                          "from_member": "Nobody", "to_member": "Member02"}]}
    assert _check(_answer(facts={"proposals": [proposal]})) == [
        'a counterparty in proposal "x" matches no member; name members by their league label',
    ]
    twins = {**proposal, "counterparties": ["Twin"],
             "legs": [{"kind": "term", "text": "t", "from_member": "Twin",
                       "to_member": "Member05"}]}
    assert verify(_answer(facts={"proposals": [twins]}), SNAPSHOT, TWINS, PLAYERS) == [
        'a counterparty in proposal "x" could mean more than one member; ask which'
    ]


def test_an_unresolved_player_is_not_echoed_either() -> None:
    unknown = _answer(facts={"players": [{"name": "Nobody Special", "holder": "Member05"}]})
    assert _check(unknown) == [
        "a player in the facts matches no known player; name players by their full name"
    ]
    vague = _answer(facts={"players": [{"name": "Bench", "holder": "Member05"}]})
    assert _check(vague) == ["a player in the facts could mean more than one player; ask which"]
    leg = {"kind": "player", "player_name": "Nobody Special",
           "from_member": "Member05", "to_member": "Member02"}
    proposal = {"title": "x", "counterparties": ["Member02"], "legs": [leg]}
    assert _check(_answer(facts={"proposals": [proposal]})) == [
        'a player in the proposal matches no known player; name players by their full name'
    ]


def test_an_id_the_directory_lacks_is_still_found_on_a_roster() -> None:
    thin = {k: v for k, v in PLAYERS.items() if k != "p05b0"}
    assert verify(_answer(), SNAPSHOT, MEMBERS, thin) == []
    renamed = {"player_id": "not-an-id", "name": "Bench 05-0", "holder": "Member05"}
    assert _check(_answer(facts={"players": [renamed]})) == [
        "a player in the facts has an unknown player id"
    ]


def test_a_sentence_that_would_repeat_an_unpublished_token_is_replaced() -> None:
    proposal = {"title": "ben@example.com", "counterparties": ["Nobody"],
                "legs": [{"kind": "term", "text": "t", "from_member": "Member02",
                          "to_member": "Member05"}]}
    assert _check(_answer(facts={"proposals": [proposal]})) == [UNPUBLISHED]
    report = {"title": "t", "question": "q", "html_body": "<p>x</p>",
              "sources": [{"url": "http://ben@example.com/x", "claim": "c"}]}
    assert _check(_answer(report=report)) == [UNPUBLISHED]
    # The privacy findings themselves are exempt: "mentions dues" is a finding, not a leak.
    assert _check(_answer(chat_text="dues are late")) == ["the chat text mentions dues"]
