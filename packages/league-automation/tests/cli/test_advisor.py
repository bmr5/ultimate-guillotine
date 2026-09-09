"""`ug advisor ask`: the dry run, exercised the way an operator runs it.

Every test here drives the command in a subprocess, with no database and no
Hermes profile in reach, because that is the claim being tested: `--fixture
--json` prints the whole candidate set the model would have been handed while
touching nothing at all. A test that imported the handler and stubbed its
dependencies would prove the handler works; this proves the command does.
"""

import json
import os
import subprocess
import sys

ASK = [sys.executable, "-m", "ultimate_guillotine.cli.main", "advisor", "ask"]
QUESTION = "@bot I need a RB rental for the next 2 weeks"
#: A member of the fixture league, which is who `--fixture` can be asked as.
MEMBER = "Member18"
#: No database, no delivery: a run that reached for either would fail loudly
#: rather than quietly using the operator's real settings.
BARE_ENV = {
    key: value
    for key, value in os.environ.items()
    if key not in ("DATABASE_URL", "TEST_DATABASE_URL", "DELIVERY_MODE")
}


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*ASK, *args], capture_output=True, text=True, check=False, env=BARE_ENV, timeout=60
    )


def test_advisor_help_lists_ask() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "advisor", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "ask" in result.stdout


def test_ask_help_documents_the_dry_run_flags() -> None:
    result = run("--help")
    assert result.returncode == 0
    for flag in ("--text", "--as", "--json", "--fixture"):
        assert flag in result.stdout


def test_a_fixture_json_run_prints_the_candidate_set_and_touches_nothing() -> None:
    result = run("--fixture", "--json", "--text", QUESTION, "--as", MEMBER)

    assert result.returncode == 0, result.stderr
    candidates = json.loads(result.stdout)
    assert candidates
    for candidate in candidates:
        assert candidate["counterparty"].startswith("Member")
        assert candidate["structure"] == "rental"
        assert candidate["return_condition"]
        legs = candidate["asker_receives"] + candidate["asker_sends"]
        assert all(leg["kind"] in ("player", "faab") for leg in legs)


def test_the_printed_candidate_set_carries_nothing_private() -> None:
    result = run("--fixture", "--json", "--text", QUESTION, "--as", MEMBER)

    body = result.stdout.lower()
    for forbidden in ("chat_guid", "sender_hash", "handle", "dues", "imessage;", "+1555"):
        assert forbidden not in body


def test_an_unresolvable_member_exits_two_without_asking_anything() -> None:
    result = run("--fixture", "--json", "--text", QUESTION, "--as", "Nobody At All")

    assert result.returncode == 2
    assert "unknown member" in result.stderr
    assert result.stdout == ""


def test_a_member_is_matched_however_it_is_capitalized() -> None:
    result = run("--fixture", "--json", "--text", QUESTION, "--as", "member18")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)
