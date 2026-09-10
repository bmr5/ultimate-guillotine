import os

import pytest

from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.ai.structured import AIUsage
from ultimate_guillotine.config import Settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.trades.extract import PROMPT_VERSION, extract_trade, load_prompt
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade


class FakeAI:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, system, user, schema, schema_name):
        self.calls.append((system, user, schema, schema_name))
        return self.result, AIUsage("gen-1", 10, 5, "m")


def test_prompt_is_versioned_and_states_the_rules() -> None:
    prompt = load_prompt()
    assert PROMPT_VERSION == "2026.4"
    assert prompt.startswith(f"<!-- prompt_version: {PROMPT_VERSION} -->")
    assert "verbatim" in prompt and "null" in prompt and "fairness" in prompt


def test_prompt_explains_rentals_and_keeps_special_terms_for_other_conditions() -> None:
    prompt = load_prompt()
    assert "`rental_return_condition` (for example `50 FAAB returned Monday`)" in prompt
    assert "use `special_terms` only for other unusual conditions" in prompt


def test_prompt_orders_not_a_trade_before_unclear_and_scopes_naming() -> None:
    prompt = load_prompt()
    assert "Decide `not_a_trade` first" in prompt
    assert "Only when the message announces a transaction" in prompt
    assert "in the announcement itself" in prompt
    assert "one-sentence `unclear_reason`" in prompt
    assert prompt.index("Decide `not_a_trade` first") < prompt.index("`unclear_reason`")


#: The rules 2026.2, 2026.3 and 2026.4 added, each as the phrase the prompt has to carry. Kept as a
#: table so a rule quietly dropped from the prompt fails under its own name --
#: the suite proves the prompt still says these things, never what the model
#: does with them, which is what `scripts/registrar_cases.py` is for.
PROMPT_RULES_2026_4 = [
    (
        "a report of an alert is not an announcement",
        "A message that reports or reacts to an alert instead of making one is `not_a_trade`",
    ),
    (
        "quoting or forwarding someone else's alert",
        "quoting or forwarding someone else's alert, or commenting on one",
    ),
    (
        "an aside on your own alert is still an announcement",
        "An aside attached to the announcer's own alert",
    ),
    (
        "a message with no transaction in it is not_a_trade",
        "A message with no transaction in it at all",
    ),
    (
        "a bare header or siren is not the unclear case",
        "is `not_a_trade` and never `unclear`",
    ),
    (
        "another league's trade names no member and is placed elsewhere",
        "`League members` list *and* places the trade somewhere else",
    ),
    (
        "naming nobody on its own is unclear, not not_a_trade",
        "an alert that names no member but places the trade nowhere else is `unclear`",
    ),
    (
        "one named member is enough",
        "One league member named in the announcement is enough to make it this league's alert",
    ),
    (
        "first person names the announcer",
        "First-person references -- `I`, `me`, `my`, `my team`, `mine` -- name the announcer",
    ),
    (
        "first person is read as the announcer's username written there",
        "read them exactly as if the announcer's Sleeper username were written in their place",
    ),
    (
        "an unknown announcer makes first person name nobody",
        "When `Announcer:` is `unknown`, first-person references name nobody",
    ),
    (
        "an announcement resting on one names fewer than two people",
        "names fewer than two people and is `unclear`",
    ),
    (
        "second person names nobody by default",
        "Second-person references -- `you`, `your guy` -- name nobody",
    ),
    (
        "you is the one member named besides the announcer",
        (
            "unless the announcement names exactly one league member besides the announcer,"
            " in which case `you` is that member"
        ),
    ),
    (
        "you is never the other side of the same transfer",
        "`you` is never the person on the other side of the same transfer",
    ),
    (
        "a player is spelled the way the rosters spell him",
        "Write each player exactly as it is spelled there",
    ),
    (
        "a partial name is resolved on the giving party's roster",
        (
            "find that player on the *giving* party's roster and copy his full name from"
            " `Rosters` into `player_name`"
        ),
    ),
    (
        "an unknown giver widens the search to every roster",
        "If the giving party is not known, look across every roster",
    ),
    (
        "a name on nobody's roster is left as written",
        "A name that matches nobody's roster is left exactly as the announcement wrote it",
    ),
    (
        "the rosters are a spelling aid, never an ownership check",
        "`Rosters` says how a name is spelled. It never says who is allowed to trade whom",
    ),
    (
        "a roster that disagrees with the announcement does not make it unclear",
        "never answer `unclear` because a roster disagrees with it",
    ),
    (
        "an uncoded rescission names its trade from the season's list",
        "use that list to find the one it means and copy that trade's code",
    ),
    (
        "an ambiguous or absent match leaves the code null",
        "If two or more fit, or none does, leave `referenced_trade_code` as `null`",
    ),
    (
        "FAAB a team cannot pay is unclear, never quietly corrected",
        (
            "if an announcement has a team paying more FAAB than it has left, set `kind` to"
            " `unclear` and say so in one sentence"
        ),
    ),
    (
        "only the FAAB section can make an announcement unclear",
        "`FAAB remaining` is the only context section that can make an announcement `unclear`",
    ),
    (
        "context helps you read an announcement, never doubt it",
        (
            "an announcement that is clear on its own stays clear, however little of it the"
            " rosters and the trade list happen to corroborate"
        ),
    ),
    (
        "the current week is what a relative week means",
        "`next week` is that number plus one",
    ),
    (
        "the current week still does not state a week",
        "set `effective_week` only when the announcement gives one",
    ),
    (
        "unstated direction is unclear, with a reason",
        "Also `unclear`, with a one-sentence `unclear_reason`:",
    ),
    (
        "unstated direction is the never-says-which-side case",
        "names the people and the assets but never says which side gives what",
    ),
    (
        "what does count as stating direction",
        "Direction is stated by words and marks like `sends`, `to`, `for`, `gets`, `->`",
    ),
    (
        "the league's two budgets have one exchange rate",
        "every $1 of unspent draft budget became $5 of FAAB at the start of the season",
    ),
    (
        "a draft-dollar price is a FAAB price",
        (
            "an amount stated in **draft dollars** -- `draft dollars`, `draft FAAB`,"
            " `auction dollars`, `draft budget`, `$13 draft` -- is a FAAB price written the other"
            " way round"
        ),
    ),
    (
        "the converted amount is what is written",
        "`amount` five times the stated number",
    ),
    (
        "the announcement's own phrase is kept in the label",
        "copy the announcement's own phrase into `description`",
    ),
    (
        "the currency field is the alternative to converting",
        "write the number exactly as the announcement states it and set `currency` to `draft`",
    ),
    (
        "a draft figure left as faab records a fifth of what was paid",
        "Never write a draft-dollar figure with `currency` left as `faab`",
    ),
    (
        "usd is neither budget",
        "`currency` is `faab` for every other amount, including `usd`",
    ),
    (
        "a price stated both ways must agree at five to one",
        "the two must agree at five to one",
    ),
    (
        "one price written twice is one asset, never two",
        "never two assets that would be added together",
    ),
    (
        "two prices that disagree are unclear with a reason",
        "set `kind` to `unclear` and say in one sentence which two amounts disagree",
    ),
    (
        "the league rules are what make the rest of the context mean anything",
        "The `League rules:` section is the league's own rules, curated",
    ),
    (
        "the rules are read to understand an announcement, never to judge one",
        "Read it the way you read the rosters -- to understand an announcement, never to judge one",
    ),
    (
        "a trade the rules would not allow is still the trade that was announced",
        "the commissioner vetoes trades, and you are not the commissioner",
    ),
]


@pytest.mark.parametrize(
    ("rule", "phrase"),
    PROMPT_RULES_2026_4,
    ids=[rule for rule, _ in PROMPT_RULES_2026_4],
)
def test_prompt_states_the_2026_4_rules(rule: str, phrase: str) -> None:
    # The prompt wraps at 100 columns, so match against it as one flowing line.
    assert phrase in " ".join(load_prompt().split())


def test_prompt_keeps_the_not_a_trade_rules_ahead_of_the_unclear_rules() -> None:
    """Order is the rule: a report of someone else's alert has to be answered
    `not_a_trade` before the direction test can turn it into a clarification."""
    prompt = " ".join(load_prompt().split())
    assert prompt.index("reports or reacts to an alert") < prompt.index("`unclear_reason`")
    assert prompt.index("names nobody from the `League members` list") < prompt.index(
        "never says which side gives what"
    )


def test_prompt_marks_the_user_message_context_lines_as_never_announcement() -> None:
    prompt = load_prompt()
    assert (
        "The user message's `Season:`, `Week hint:`, `League members`, `Announcer:`,"
        " `Current NFL week:`,\n`Rosters:`, `FAAB remaining:`, `Trades this season:` and"
        " `League rules:` lines are"
        in prompt
    )
    assert "context, never announcement content" in prompt
    # The one exception, and the reason the announcer line is not just more context:
    # a first-person reference *is* the announcement naming the person who posted it.
    assert "A name that appears only on those lines is not named, except" in prompt
    assert "through a first- or second-person reference" in prompt
    assert "The `Week hint:` line is context and never counts as the announcement" in prompt


def test_prompt_explains_referenced_trade_code_and_asset_fields() -> None:
    prompt = load_prompt()
    assert "a code such as `T-2026-014`" in prompt
    assert "copy that code into `referenced_trade_code`" in prompt
    assert "`from_party` is the person who gives the asset" in prompt
    assert "`to_party` is the person who receives it" in prompt
    assert "`protection` is for gulag protection" in prompt
    assert "Use asset `kind` `other` for anything else" in prompt
    assert "verbatim `description`" in prompt


def test_extract_passes_context_and_returns_model_output() -> None:
    expected = ExtractedTrade(
        kind="rental", parties=[ExtractedParty(name="Member03"), ExtractedParty(name="Member04")],
        assets=[ExtractedAsset(kind="player", from_party="Member04", to_party="Member03", player_name="Player Beta", amount=None, unit=None, description=None),
                ExtractedAsset(kind="faab", from_party="Member03", to_party="Member04", player_name=None, amount=92, unit="faab", description=None)],
        effective_week=2, rental_return_condition="50 FAAB returned Monday", special_terms=[], referenced_trade_code=None, unclear_reason=None,
    )
    ai = FakeAI(expected)
    result, usage = extract_trade(ai, "🚨 Member03 rents Player Beta from Member04 for 92 FAAB, 50 returned Monday", 2026, 2, ["Member03", "Member04"])
    assert result == expected and usage.response_id == "gen-1"
    system, user, schema, name = ai.calls[0]
    assert schema is ExtractedTrade and name == "extracted_trade"
    assert "Member03" in user and "Season: 2026" in user and "Week hint: 2" in user
    assert system == load_prompt()


def test_extract_writes_the_exact_context_lines() -> None:
    ai = FakeAI(ExtractedTrade(kind="not_a_trade"))
    extract_trade(ai, "Member03 rents Player Beta", 2026, 2, ["Member03", "Member04"])
    lines = ai.calls[0][1].splitlines()
    assert "Season: 2026" in lines
    assert "Week hint: 2" in lines
    assert "League members (Sleeper username: names people use): Member03; Member04" in lines

    extract_trade(ai, "Member03 rents Player Beta", 2026, None, ["Member03", "Member04"])
    assert "Week hint: unknown" in ai.calls[1][1].splitlines()


def test_the_announcer_line_names_the_sender_or_says_unknown() -> None:
    """The line is always written, and always right after the members list: the
    prompt's first-person rule reads both, and an absent line has no rule."""
    ai = FakeAI(ExtractedTrade(kind="not_a_trade"))
    extract_trade(ai, "I sent Player Beta to Member04", 2026, None, ["Member03", "Member04"])
    lines = ai.calls[0][1].splitlines()
    assert "Announcer: unknown" in lines

    extract_trade(
        ai, "I sent Player Beta to Member04", 2026, None, ["Member03", "Member04"], "Member03"
    )
    lines = ai.calls[1][1].splitlines()
    assert "Announcer: Member03" in lines
    members = "League members (Sleeper username: names people use): Member03; Member04"
    assert lines.index("Announcer: Member03") == lines.index(members) + 1


def test_the_context_pack_goes_between_the_announcer_and_the_announcement() -> None:
    """Last thing read is the announcement itself; everything before it is what
    the prompt calls context, and the pack is more of the same."""
    ai = FakeAI(ExtractedTrade(kind="not_a_trade"))
    pack = "Current NFL week: 4\n\nRosters:\nMember03 (no known nicknames): Player Beta RB"
    extract_trade(
        ai, "Member03 sends Beta", 2026, None, ["Member03", "Member04"], "Member03", pack
    )
    user = ai.calls[0][1]
    assert pack in user
    assert user.index("Announcer: Member03") < user.index(pack) < user.index("Announcement:")


def test_no_context_pack_writes_no_section_at_all() -> None:
    """An empty `Rosters:` heading would tell the model every roster is empty,
    which is a claim; leaving the section out tells it nothing, which is true."""
    ai = FakeAI(ExtractedTrade(kind="not_a_trade"))
    extract_trade(ai, "Member03 sends Beta", 2026, None, ["Member03", "Member04"])
    user = ai.calls[0][1]
    assert "Rosters:" not in user and "Current NFL week" not in user
    assert user.splitlines()[-2:] == ["Announcement:", "Member03 sends Beta"]


@pytest.mark.skipif(
    os.environ.get("UG_LIVE_AI_TESTS") != "1",
    reason="live model calls cost credits; set UG_LIVE_AI_TESTS=1 to run them",
)
def test_live_extraction_reads_a_simple_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one test that spends the subscription. A configured Hermes profile is
    not consent to call it, so this asks for the flag as well.

    `PYTEST_CURRENT_TEST` is dropped from this process's environment, and so from
    the CLI's: Hermes reads it as "I am running inside my own test suite" and then
    refuses to open the real user's auth store, which leaves the call with no
    credentials. Nothing in the package sets that variable, so only a test run is
    ever affected; it is dropped here rather than in the client so that the client
    keeps handing the CLI the environment it was actually given. Hermes still
    declines to write a session row, which is exactly right for a test.
    """
    if find_hermes_binary() is None:
        pytest.skip("hermes CLI not found")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    client = HermesStructuredClient(Settings.model_fields["hermes_profile_home"].default)
    result, _usage = extract_trade(
        client,
        "🚨 Trade Alert 🚨\nMember01 sends Player Alpha to Member02 for 100 FAAB",
        2026,
        None,
        ["Member01: Ben, Benny", "Member02: no known nicknames"],
    )
    assert result.kind == "permanent"
    assert len(result.parties) == 2
    faab = [asset for asset in result.assets if asset.unit == "faab"]
    assert len(faab) == 1
    assert faab[0].amount == 100


def test_prompt_names_every_asset_kind_and_ties_units_to_money_kinds() -> None:
    # The prompt wraps at 100 columns, so match against it as one flowing line.
    prompt = " ".join(load_prompt().split())
    assert (
        "Asset `kind` is one of `player`, `faab` (waiver budget), `usd` (real money), "
        "`draft_dollars` (auction budget), `protection`, or `other`." in prompt
    )
    assert "`unit` must match the kind" in prompt
