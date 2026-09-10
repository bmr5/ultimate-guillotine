from ultimate_guillotine.ai.structured import AIUsage
from ultimate_guillotine.video.copy import TradeCopy
from ultimate_guillotine.video.script import (
    SCHEMA_NAME,
    SYSTEM,
    Beat,
    Script,
    format_script,
    generate_script,
    normalize,
    script_from_text,
    script_seconds,
    seconds_for,
    spoken,
    template_script,
    word_budget,
)

COPY = TradeCopy(
    caption="pov: the league chat when Derek and Charlie pull off a trade nobody saw coming",
    headline="SOURCES: JOSH JACOBS TRADED TO CHARLIE",
    subline="Derek gets 450 FAAB · Charlie gets Josh Jacobs · Week 3",
)
USAGE = AIUsage("r1", 10, 10, "test")


def test_word_budget_is_two_point_six_words_a_second() -> None:
    assert word_budget(12) == 31
    assert word_budget(8) == 20


def test_template_read_speaks_the_headline_and_terms_within_budget() -> None:
    script = template_script(COPY, 12)
    assert script.read.startswith(
        "Breaking news. Sources tell ESPN: Josh Jacobs traded to Charlie."
    )
    assert "Derek gets 450 dollars, Charlie gets Josh Jacobs." in script.read
    assert "FAAB" not in script.read
    assert "Week 3" not in script.read
    assert script.words <= word_budget(12)
    assert script.beats[0].start == 0.0 and script.beats[-1].end == 12


def test_template_read_drops_its_closer_when_the_clip_is_short() -> None:
    script = template_script(COPY, 6)
    assert script.words <= word_budget(6) or len(script.beats) == 2


def test_a_typed_read_is_one_beat_across_the_clip() -> None:
    script = script_from_text("Breaking news. Josh Jacobs is on the move.", 8)
    assert [(b.start, b.end) for b in script.beats] == [(0.0, 8)]


def test_normalize_orders_clamps_and_runs_the_last_beat_to_the_end() -> None:
    script = Script(
        beats=[
            Beat(start=5, end=20, direction="b", text="second"),
            Beat(start=0, end=4, direction="a", text="first"),
            Beat(start=6, end=7, direction="c", text="   "),
        ]
    )
    fixed = normalize(script, 10)
    assert [b.text for b in fixed.beats] == ["first", "second"]
    assert fixed.beats[-1].end == 10 and fixed.beats[1].start == 5


class LongThenShort:
    """A model that runs long once, then fits."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def parse(self, system, user, schema, schema_name):
        self.calls.append(user)
        assert schema is Script and schema_name == SCHEMA_NAME
        if len(self.calls) == 1:
            text = "word " * 60
        else:
            text = "Breaking news. Sources tell ESPN Josh Jacobs is headed to Charlie."
        return Script(beats=[Beat(start=0, end=12, direction="urgent", text=text)]), USAGE


def test_generate_script_sends_a_long_read_back_once() -> None:
    client = LongThenShort()
    script = generate_script(client, COPY, 12)
    assert len(client.calls) == 2
    assert "Your previous read was 60 words; the limit is 31" in client.calls[1]
    assert "Word limit: 31 words" in client.calls[0]
    assert "SOURCES: JOSH JACOBS TRADED TO CHARLIE" in client.calls[0]
    assert "450 dollars" in client.calls[0] and "FAAB" not in client.calls[0]
    assert script.words == 11 and script.beats[-1].end == 12


def test_format_script_lists_beats_and_the_count() -> None:
    text = format_script(template_script(COPY, 12), 12)
    assert text.startswith("00:00-00:02  (leans in, urgent) Breaking news.")
    assert text.endswith("words for 12 s (budget 31)")


def test_the_read_says_dollars_never_faab() -> None:
    assert spoken("Derek gets 450 FAAB · Charlie gets 20 FAAB + Player Alpha") == (
        "Derek gets 450 dollars · Charlie gets 20 dollars and Player Alpha"
    )
    assert spoken("30 draft dollars") == "30 draft dollars"
    assert "never say FAAB" in SYSTEM


def test_the_clip_is_sized_to_the_read_between_4_and_15_seconds() -> None:
    def script_of(words: int) -> Script:
        return Script(beats=[Beat(start=0, end=1, direction="d", text=" ".join(["w"] * words))])

    assert seconds_for(script_of(14)) == 7  # ceil(14 / 2.6) = 6, plus a second of air
    assert seconds_for(script_of(20)) == 9
    assert seconds_for(script_of(3)) == 4
    assert seconds_for(script_of(60)) == 15


def test_template_and_typed_reads_size_themselves_when_no_length_is_given() -> None:
    script = template_script(COPY)
    assert script_seconds(script) == seconds_for(script)
    assert script.beats[-1].end == seconds_for(script)
    typed = script_from_text("Breaking news. Josh Jacobs is on the move.", None)
    assert script_seconds(typed) == 5  # 8 words: ceil(8 / 2.6) + 1


class ShortAnswer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def parse(self, system, user, schema, schema_name):
        self.calls.append(user)
        text = "Breaking news. Sources tell ESPN Josh Jacobs is headed to Charlie for four hundred fifty dollars."
        return Script(beats=[Beat(start=0, end=6, direction="urgent", text=text)]), USAGE


def test_generate_script_with_no_length_asks_for_the_shortest_read_and_sizes_the_clip() -> None:
    client = ShortAnswer()
    script = generate_script(client, COPY)
    assert "as short as the facts allow, up to 15 seconds" in client.calls[0]
    assert "Word limit: 39 words" in client.calls[0]
    assert script.words == 16 and script_seconds(script) == seconds_for(script) == 8


def test_the_brief_lists_the_facts_in_dollars() -> None:
    copy = TradeCopy(
        caption=COPY.caption,
        headline=COPY.headline,
        subline=COPY.subline,
        facts=(
            "Announced in the league chat as: 🚨 Trade alert 🚨 Derek sends Josh Jacobs to "
            "Charlie for 450 FAAB",
            "Derek gives Charlie: Josh Jacobs",
            "Charlie gives Derek: 450 FAAB",
        ),
    )
    client = ShortAnswer()
    generate_script(client, copy)
    brief = client.calls[0]
    assert (
        "The trade, fact by fact (state only these):\n- Announced in the league chat as:" in brief
    )
    assert "- Charlie gives Derek: 450 dollars\n" in brief
    assert "FAAB" not in brief


def test_the_writer_knows_the_gulag_and_the_commish() -> None:
    assert "the announcement wins" in SYSTEM
    assert "gulag" in SYSTEM and "whoever pays stays out" in SYSTEM
    assert "'the Commish' on air" in SYSTEM
