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
        "Derek gets 450 dollars · Charlie gets 20 dollars + Player Alpha"
    )
    assert spoken("30 draft dollars") == "30 draft dollars"
    assert "never say FAAB" in SYSTEM
