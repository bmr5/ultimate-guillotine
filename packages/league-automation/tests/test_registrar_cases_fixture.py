"""Shape checks for the Trade Registrar case suite.

`scripts/registrar_cases.py` reads this fixture and trusts it: an unknown status
would raise a `KeyError` in the middle of an overnight run, and a `prereq`
pointing at nothing would silently skip a case forever. Both are cheap to catch
here instead.
"""

import json
from pathlib import Path

import pytest

from ultimate_guillotine.core.signature import is_signed

FIXTURE = Path(__file__).parent / "fixtures" / "registrar_cases.json"
KEYS = {"id", "category", "text", "expected_kind", "expected_status", "prereq", "notes"}
#: `announcer` is optional and names the member the alert was sent by, as the
#: listener would place them from the sender's handle. A case without it is a
#: case whose sender could not be placed, which is a different answer rather
#: than a missing field -- so the key is absent, never `null`.
OPTIONAL_KEYS = {"announcer"}
KINDS = {"permanent", "rental", "payment", "rescission", "unclear", "not_a_trade"}
STATUSES = {
    "created",
    "revised",
    "duplicate",
    "rescinded",
    "clarification",
    "not_a_trade",
    #: Never reaches the agent at all -- the listener drops it first.
    "dropped_upstream",
}
CATEGORIES = {
    "happy",
    "sloppy",
    "revision",
    "duplicate",
    "rescission",
    "not_a_trade",
    "unclear",
    "privacy",
    "scale",
}
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_suite_is_the_agreed_size() -> None:
    assert 60 <= len(CASES) <= 90


def test_ids_are_unique_and_contiguous() -> None:
    assert [case["id"] for case in CASES] == list(range(1, len(CASES) + 1))


def test_every_category_is_covered() -> None:
    assert {case["category"] for case in CASES} == CATEGORIES


@pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
def test_case_shape(case: dict) -> None:
    assert KEYS <= set(case) <= KEYS | OPTIONAL_KEYS
    if "announcer" in case:
        assert isinstance(case["announcer"], str) and case["announcer"].strip()
    assert case["category"] in CATEGORIES
    assert case["expected_kind"] in KINDS
    assert case["expected_status"] in STATUSES
    assert isinstance(case["text"], str) and case["text"].strip()
    assert isinstance(case["notes"], str) and case["notes"].strip()


@pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
def test_prerequisites_point_at_an_earlier_case(case: dict) -> None:
    """A prereq has to exist and has to come first: the runner logs cases in id
    order, so a forward reference would never be on file when it was needed."""
    prereq = case["prereq"]
    if prereq is None:
        return
    assert isinstance(prereq, int)
    assert prereq in {other["id"] for other in CASES}
    assert prereq < case["id"]


def test_states_needing_prior_state_declare_a_prerequisite() -> None:
    """`revised`, `duplicate` and `rescinded` are only reachable once something
    is already on file, so each of those cases must name what it depends on."""
    for case in CASES:
        if case["expected_status"] in {"revised", "duplicate", "rescinded"}:
            assert case["prereq"] is not None, case["id"]


def test_dropped_upstream_cases_are_ones_the_listener_really_drops() -> None:
    """`dropped_upstream` is a claim about the listener, not a way to excuse a
    case the model gets wrong: the listener drops a message because the bot
    signed it, so the text has to carry that signature."""
    dropped = [case for case in CASES if case["expected_status"] == "dropped_upstream"]
    assert dropped
    for case in dropped:
        assert is_signed(case["text"]), case["id"]


def test_the_first_person_pair_differs_only_by_its_announcer() -> None:
    """Cases 74 and 75 are the same announcement sent by somebody and by nobody.
    If the texts ever drift apart the pair stops proving what it exists for: that
    the announcer, and not the wording, is what turns `I` into a party."""
    with_announcer = next(c for c in CASES if c["id"] == 74)
    without = next(c for c in CASES if c["id"] == 75)
    assert with_announcer["text"] == without["text"]
    assert "announcer" in with_announcer and "announcer" not in without
    assert with_announcer["expected_status"] == "created"
    assert without["expected_status"] == "clarification"


def test_every_announcer_is_named_somewhere_the_members_list_can_reach() -> None:
    """The runner matches the announcer against `public.members`, so a username
    with a stray space or a display-name spelling would silently fail the case."""
    for case in CASES:
        announcer = case.get("announcer")
        if announcer is not None:
            assert announcer == announcer.strip()
            assert " " not in announcer, case["id"]
